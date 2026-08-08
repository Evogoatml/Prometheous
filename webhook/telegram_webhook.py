
"""
Webhook handler for Prometheous Telegram bot.

Optional alternative to long-polling. Exposes a FastAPI/Flask endpoint
that Telegram sends updates to. Requires a public URL (ngrok, cloudflared).

Usage:
  uvicorn webhook.telegram_webhook:app --host 0.0.0.0 --port 8080
  ngrok http 8080
  curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<ngrok>/telegram"
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from core.gateway import gateway
from swarm.bridge import NOOP_REPLY, InboundGuard

logger = logging.getLogger(__name__)


class TelegramWebhookHandler:
    def __init__(self) -> None:
        self._token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
        self._guard = InboundGuard()

    def _send(self, text: str, chat_id: str) -> Dict[str, Any]:
        if not self._token:
            return {"status": "failed", "error": "bot token missing"}
        import requests

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
            r.raise_for_status()
            return {"status": "ok", "sent": r.json().get("result", {}).get("message_id")}
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}

    def handle_update(self, update: Dict[str, Any]) -> Dict[str, Any]:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return {"status": "skipped", "reason": "no_message"}

        if msg.get("from", {}).get("is_bot"):
            return {"status": "skipped", "reason": "bot_message"}

        text = (msg.get("text") or "").strip()
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if not text or not chat_id:
            return {"status": "skipped", "reason": "empty_or_no_chat_id"}

        try:
            ts = float(msg.get("date") or time.time())
            cid = str(chat_id)
            if not self._guard.should_process(cid, text, ts):
                return {"status": "throttled", "chat_id": cid}
            if self._guard.is_noop(text) and self._guard.allow_noop_reply(cid, ts):
                self._send(NOOP_REPLY, cid)
                return {"status": "skipped", "reason": "noop"}

            result = gateway.handle(text, context={"channel": "telegram", "chat_id": cid})
            if result.reply:
                self._send(result.reply, cid)
            return {"status": "dispatched", "chat_id": cid}
        except Exception as e:
            logger.error("webhook dispatch failed: %s", e)
            return {"status": "failed", "error": str(e)}


# FastAPI app (optional)
try:
    from fastapi import FastAPI, Request

    app = FastAPI()
    handler = TelegramWebhookHandler()

    @app.post("/telegram")
    async def telegram_webhook(request: Request):
        update = await request.json()
        return handler.handle_update(update)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

except ImportError:
    app = None  # type: ignore[assignment]
    logger.info("FastAPI not installed — webhook server unavailable")