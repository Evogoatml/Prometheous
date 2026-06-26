
"""
Telegram interface for Prometheous.

Embeds the long-poll / webhook Telegram bot as a swarm agent
(telegram_bot.py in agents/) so the same orchestrator pipeline
processes incoming user messages.
"""
import logging
import os
from typing import Any, Dict, Optional

from swarm.base import BaseAgent

logger = logging.getLogger(__name__)


class TelegramAgent(BaseAgent):
    name = "telegram"
    role = "Telegram"
    specialty = "Telegram user-facing I/O gateway"

    def __init__(self):
        super().__init__()
        self._token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
        self._chat_id: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")
        self._running: bool = False

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
          {"mode": "send", "text": "..."}        — send a message
          {"mode": "start", "poll_interval": 2}  — start long-poll loop
          {"mode": "stop"}                        — stop the loop
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

        return {"status": "failed", "agent": self.name, "error": f"unknown mode: {mode}"}

    # private -------------------------------------------------------------
    def _send(self, text: str) -> Dict[str, Any]:
        if not text:
            return {"status": "failed", "agent": self.name, "error": "empty text"}
        try:
            import requests  # type: ignore  # optional dep
        except ImportError:
            return {"status": "failed", "agent": self.name, "error": "requests not installed (pip install requests)"}

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            r = requests.post(url, json={"chat_id": self._chat_id, "text": text}, timeout=10)
            r.raise_for_status()
            return {"status": "ok", "agent": self.name, "sent": r.json().get("result", {}).get("message_id")}
        except Exception as e:
            return {"status": "failed", "agent": self.name, "error": str(e)}

    def _start(self, poll_interval: int = 2) -> Dict[str, Any]:
        if self._running:
            return {"status": "ok", "agent": self.name, "note": "already running"}
        self._running = True
        logger.info("telegram agent starting long-poll (interval=%ds)", poll_interval)
        # Real polling should run in a background thread/process.
        # For now this just records the intent; the main loop drives it.
        return {"status": "ok", "agent": self.name, "note": f"polling started (interval {poll_interval}s), but background not yet implemented"}

    # alternative: register with the orchestrator via on_deploy
    # so the system automatically wraps this as an agent.
