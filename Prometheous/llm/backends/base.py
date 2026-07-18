"""
LLM backend base class.

A backend is a single chat-completions-style provider: it takes a
system prompt + user message (plus optional conversation history)
and returns a string. It must also report whether it is currently
usable (key present, model known, not in cooldown).

Cooldowns live in a module-level dict (`_COOLDOWNS`) keyed by backend
name, so the dispatch loop can rebuild backend instances every call
(config changes picked up live) without losing the per-backend back-off
state.

Concrete backends live in llm.backends.{openai,grok,ollama,...}.
The dispatch loop in llm.client iterates the registered backends in
priority order; this ABC exists so adding a 4th provider is a 1-file change.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Sequence


# backend_name -> epoch-seconds when cooldown ends
_COOLDOWNS: Dict[str, float] = {}


def is_live(name: str) -> bool:
    """True if the named backend is past its cooldown (or never set)."""
    return time.time() > _COOLDOWNS.get(name, 0.0)


def cooldown_remaining(name: str) -> float:
    return max(0.0, _COOLDOWNS.get(name, 0.0) - time.time())


def mark_dead(name: str, message: str, cooldown: float) -> None:
    """Stamp a backend's cooldown. Caller computes the cooldown length."""
    _COOLDOWNS[name] = time.time() + cooldown


class Backend(ABC):
    name: str = "abstract"

    @abstractmethod
    def available(self) -> bool:
        """True if this backend is configured and not in cooldown."""

    @abstractmethod
    def respond(
        self,
        system_output: Dict[str, Any],
        user_msg: str,
        *,
        history: Optional[Sequence[Dict[str, str]]] = None,
    ) -> str:
        """Return a natural-language reply, or raise on error.

        Implementations should build messages via llm.conversation.build_messages
        and the module-level PROMETHEOUS_SYSTEM_PROMPT in llm.client.
        """
