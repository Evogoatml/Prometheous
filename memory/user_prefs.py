"""
User preferences — encrypted vault-backed per-chat_id settings.

Stored as a dict-of-dicts under the key "user_prefs":
    {
        "<chat_id>": {
            "name": str | None,
            "last_agent": str | None,
            "last_intent": str | None,
            "command_count": int,
            "first_seen": float,
            "last_seen": float,
        },
        ...
    }

DecisionEngine consults this on ambiguous intents ("chat" fallback, low
confidence) to bias the next dispatch.

Why encrypted: chat_id mappings are PII-adjacent. The vault already
exists (memory.vault.EncryptedVault) and is on-disk AES-GCM. We reuse it.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from memory.vault import EncryptedVault

_VAULT = EncryptedVault()
_KEY = "user_prefs"


def _load() -> Dict[str, Dict[str, Any]]:
    return _VAULT.get(_KEY, default={}) or {}


def _save(data: Dict[str, Dict[str, Any]]) -> None:
    _VAULT.set(_KEY, data)


def get_prefs(chat_id: int) -> Dict[str, Any]:
    data = _load()
    key = str(chat_id)
    prefs = data.get(key)
    if not prefs:
        prefs = {
            "name": None,
            "last_agent": None,
            "last_intent": None,
            "command_count": 0,
            "first_seen": time.time(),
            "last_seen": time.time(),
        }
        data[key] = prefs
        _save(data)
    return prefs


def set_name(chat_id: int, name: str) -> None:
    data = _load()
    key = str(chat_id)
    prefs = data.setdefault(key, {})
    prefs["name"] = name
    prefs["last_seen"] = time.time()
    _save(data)


def record_turn(chat_id: int, intent: str, agent: Optional[str]) -> Dict[str, Any]:
    """Update prefs for a completed turn. Returns the updated prefs dict."""
    data = _load()
    key = str(chat_id)
    prefs = data.setdefault(
        key,
        {
            "name": None,
            "last_agent": None,
            "last_intent": None,
            "command_count": 0,
            "first_seen": time.time(),
            "last_seen": time.time(),
        },
    )
    prefs["last_intent"] = intent
    if agent:
        prefs["last_agent"] = agent
    prefs["command_count"] = int(prefs.get("command_count", 0)) + 1
    prefs["last_seen"] = time.time()
    _save(data)
    return prefs
