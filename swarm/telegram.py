
"""
Telegram bridge for Prometheous.

Long-poll I/O only — routing, decisions, and orchestration live in core/gateway.py.
"""
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import requests  # noqa: F401

from core.gateway import gateway
from swarm.base import BaseAgent
from swarm.bridge import NOOP_REPLY, InboundGuard

logger = logging.getLogger(__name__)


class TelegramAgent(BaseAgent):
    name = "telegram"
    role = "Telegram"
    specialty = "Telegram user-facing I/O bridge"

    def __init__(self):
        super().__init__()
        self._token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
        self._chat_id: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")
        self._running: bool = False
        self._poll_thread: Optional[threading.Thread] = None
        self._guard = InboundGuard()

    def _process_message(self, chat_id: str, text: str) -> None:
        result = gateway.handle(text, context={
            "channel": "telegram",
            "chat_id": chat_id,
            "gateway_active": self._running,
        })
        if result.reply:
            send_result = self._send(result.reply, chat_id=chat_id)
            logger.info(
                "telegram send: chat=%s status=%s message_id=%s",
                chat_id,
                send_result.get("status"),
                send_result.get("sent") or send_result.get("error"),
            )

    def _handle_inbound(self, chat_id: str, text: str, ts: float) -> str:
        """Returns status: throttled | noop | dispatched."""
        if not self._guard.should_process(chat_id, text, ts):
            return "throttled"
        if self._guard.is_noop(text) and self._guard.allow_noop_reply(chat_id, ts):
            self._send(NOOP_REPLY, chat_id=chat_id)
            return "noop"
        self._process_message(chat_id, text)
        return "dispatched"

    # lifecycle -----------------------------------------------------------
    def on_deploy(self) -> None:
        super().on_deploy()
        if not self._token:
            logger.warning("TELEGRAM_BOT_TOKEN not set — telegram agent idle")
            self.active = False

    def on_recall(self) -> None:
        super().on_recall()
        self._running = False

    # main entry ----------------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Accepts:
          {"mode": "send", "text": "..."}          — send a message
          {"mode": "start", "poll_interval": 2}    — start long-poll loop
          {"mode": "stop"}                          — stop the loop
          {"mode": "webhook", "update": {...}}      — handle one webhook update
        """
        self.tasks_completed += 1
        mode = payload.get("mode", "send")

        if mode == "send":
            return self._send(payload.get("text", ""))
        if mode == "start":
            return self._start(payload.get("poll_interval", 2))
        if mode == "stop":
            self._running = False
            return {"status": "ok", "agent": self.name, "note": "stop signal sent"}
        if mode == "webhook":
            update = payload.get("update") or {}
            msg = update.get("message") or update.get("edited_message") or {}
            text = (msg.get("text") or "").strip()
            chat = msg.get("chat") or {}
            chat_id = str(chat.get("id", ""))
            ts = float(msg.get("date") or time.time())
            if not text or not chat_id:
                return {"status": "skipped", "reason": "invalid update"}
            status = self._handle_inbound(chat_id, text, ts)
            if status == "throttled":
                return {"status": "throttled", "chat_id": chat_id}
            if status == "noop":
                return {"status": "skipped", "reason": "noop"}
            return {"status": "dispatched", "chat_id": chat_id}

        return {"status": "failed", "agent": self.name, "error": f"unknown mode: {mode}"}

    # private -------------------------------------------------------------
    def _send(self, text: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        if not text:
            return {"status": "failed", "agent": self.name, "error": "empty text"}
        if not self._token:
            return {"status": "failed", "agent": self.name, "error": "bot token missing"}

        target = chat_id or self._chat_id
        if not target:
            return {"status": "failed", "agent": self.name, "error": "no chat_id"}

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            r = requests.post(url, json={"chat_id": target, "text": text}, timeout=10)
            r.raise_for_status()
            return {"status": "ok", "agent": self.name, "sent": r.json().get("result", {}).get("message_id")}
        except Exception as e:
            return {"status": "failed", "agent": self.name, "error": str(e)}

    def _start(self, poll_interval: int = 2) -> Dict[str, Any]:
        if self._running and getattr(self, "_poll_thread", None) and self._poll_thread.is_alive():
            return {"status": "ok", "agent": self.name, "note": "already running"}

        self._running = True
        self._poll_interval = max(poll_interval, 1)

        self._poll_thread = threading.Thread(target=self._poll_loop, name="telegram-poll", daemon=True)
        self._poll_thread.start()
        logger.info("telegram bot polling started (interval=%ds)", self._poll_interval)
        return {"status": "ok", "agent": self.name, "note": f"polling started (interval {self._poll_interval}s)"}

    def _poll_loop(self) -> None:
        url = f"https://api.telegram.org/bot{self._token}/getUpdates"
        offset = 0
        backoff = self._poll_interval

        while self._running:
            try:
                params = {
                    "timeout": max(self._poll_interval * 2, 5),
                    "offset": offset,
                    "allowed_updates": ["message"],
                    "limit": 50,
                }
                r = requests.get(url, params=params, timeout=45)
                r.raise_for_status()
                data = r.json()
                if not data.get("ok"):
                    time.sleep(backoff)
                    continue

                updates = data.get("result", [])
                if updates:
                    backoff = self._poll_interval
                for update in updates:
                    offset = update["update_id"] + 1
                    msg = update.get("message") or update.get("edited_message")
                    if not msg:
                        continue
                    if msg.get("from", {}).get("is_bot"):
                        continue
                    text = (msg.get("text") or "").strip()
                    chat = msg.get("chat") or {}
                    chat_id = chat.get("id")
                    ts = float(msg.get("date", time.time()))
                    if not text or not chat_id:
                        continue
                    self._handle_inbound(str(chat_id), text, ts)

                if not updates:
                    time.sleep(max(0.2, self._poll_interval * 0.5))

            except Exception as e:
                logger.warning("telegram poll error: %s", e)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)