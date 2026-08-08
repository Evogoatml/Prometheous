"""
Shared inbound guards for Telegram transports (poll + webhook).

Dedup, rate-limit, and noop detection only — routing stays in core/gateway.py.
"""
from __future__ import annotations

from typing import Dict

NOOP_TRIGGERS = frozenset({"ping", "test", "online", "hello", "hi", "hey", "alive"})
NOOP_REPLY = "Prometheous online."


class InboundGuard:
    """Per-process dedup and rate limiting for a single bot instance."""

    def __init__(self, rate_limit_seconds: float = 1.0) -> None:
        self._recent: Dict[str, float] = {}
        self._last_reply: Dict[str, float] = {}
        self._rate_limit_seconds = rate_limit_seconds

    def should_process(self, chat_id: str, text: str, ts: float) -> bool:
        if self._is_duplicate(chat_id, text, ts):
            return False
        if text.strip().startswith("/"):
            return True
        return not self._rate_limited(chat_id, ts)

    def is_noop(self, text: str) -> bool:
        return text.strip().lower() in NOOP_TRIGGERS

    def allow_noop_reply(self, chat_id: str, ts: float) -> bool:
        """Send noop pong only when not rate-limited; records the reply slot."""
        return not self._rate_limited(chat_id, ts)

    def _is_duplicate(self, chat_id: str, text: str, ts: float) -> bool:
        key = f"{chat_id}:{text}"
        last = self._recent.get(key)
        if last and ts - last < 2.0:
            return True
        self._recent[key] = ts
        if len(self._recent) > 500:
            self._recent.clear()
        return False

    def _rate_limited(self, chat_id: str, ts: float) -> bool:
        last = self._last_reply.get(chat_id)
        if last is not None and ts - last < self._rate_limit_seconds:
            return True
        self._last_reply[chat_id] = ts
        return False