
"""
Prometheous LLM client — local-first, optional LLM for natural replies.

System decisions stay rule-based via core.decision.DecisionEngine.
This gateway phrases replies so the user feels like they're talking to
a real person who remembers the conversation — not a command parser.

Backends live in llm.backends.{openai,grok,ollama}. Adding a 4th
provider (Anthropic, Gemini, etc.) is a 1-file change: implement the
Backend ABC and register it in llm.backends.registry.DEFAULT_ORDER.

Cooldowns:
  - 429 / quota errors back off exponentially up to 1 hour
  - No retries on auth failures (401/403) until process restart
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence

try:
    from utils.config import cfg
except Exception:
    cfg = None

from llm.backends.registry import build_backends, ordered_names

logger = logging.getLogger(__name__)

ALLOWED_INTENTS = {"scan", "create_skill", "run_skill", "chat", "greet"}

# Natural voice — like a sharp friend who actually gets things done.
PROMETHEOUS_SYSTEM_PROMPT = """You are Prometheous. Talk like a real person: warm, direct, clear.

Who you are:
- A capable multi-agent system that gets work done (search, code, ads, files, learning, tools).
- Not GPT, Claude, Grok, MiniMax, or any single model product. If asked, say you're Prometheous.
- You remember the conversation and refer back to it naturally when it helps.

How you sound:
- Conversational. Contractions are fine. Short paragraphs. No corporate brochure voice.
- Don't open with "Certainly!" / "As an AI language model" / "I'd be happy to assist".
- Don't dump command menus unless they ask how to do something specific.
- Match their energy: casual in, casual out; serious in, focused out.
- When they just chat (hi, thanks, opinions, "what do you think"), answer as a person — don't invent tasks or files.
- When work already ran, report results in plain language: what you did, what you found, where files are. Lead with the outcome.

Rules:
- Never refuse with empty "I can't" if the system already produced output — report that faithfully.
- Never invent slash commands. Real ones exist as optional shortcuts only; plain language is preferred.
- Never invent agents, files, or results that aren't in the context you're given.
- Keep replies tight unless they asked for depth or you're listing real search/work results.
"""

# Only enabled when explicitly requested (default: off to avoid quota spam)
_TELEGRAM_LLM = os.getenv("PROM_TELEGRAM_LLM", "").lower() in ("1", "true", "yes")


class LLMClient:
    def __init__(self) -> None:
        self._primary = (os.getenv("PROM_LLM_PRIMARY") or "").lower().strip()
        self._fallbacks = [
            b.strip().lower()
            for b in (os.getenv("PROM_LLM_FALLBACKS") or "openai,grok,ollama").split(",")
            if b.strip()
        ]
        self._timeout = int(os.getenv("PROM_LLM_TIMEOUT", "30"))

        # Simple in-memory response cache: {prompt_signature: (ts, response_str)}
        self._cache: Dict[str, tuple[float, str]] = {}
        self._cache_ttl = int(os.getenv("PROM_LLM_CACHE_TTL", "600"))
        self._cache_max = int(os.getenv("PROM_LLM_CACHE_MAX", "256"))
        self._negative_cache: Dict[str, float] = {}
        self._negative_ttl = int(os.getenv("PROM_LLM_NEGATIVE_CACHE_TTL", "120"))

    def _backends(self) -> Dict[str, Any]:
        # Re-read every call so config changes (e.g. setting OPENAI_API_KEY)
        # are picked up without a process restart.
        return build_backends()

    # ---- public ----------------------------------------------------------
    def enabled(self) -> bool:
        return _TELEGRAM_LLM

    def maybe_call_tools(self, user_msg: str) -> Optional[Dict[str, Any]]:
        """Rule-based (+ optional LLM) tool classification."""
        from llm.tool_router import maybe_call_tools
        return maybe_call_tools(user_msg)

    def run_tool(self, user_msg: str) -> Optional[str]:
        """Classify, execute MCP tool, return formatted reply."""
        from llm.tool_router import run_tool_from_message
        return run_tool_from_message(user_msg)

    def respond(
        self,
        system_output: Dict[str, Any],
        user_msg: str,
        *,
        history: Optional[Sequence[Dict[str, str]]] = None,
    ) -> str:
        try:
            from swarm.commands import (
                format_commands_text,
                is_commands_request,
                is_context_request,
                resolve_context_reply,
            )
            if is_commands_request(user_msg):
                return format_commands_text()
            if is_context_request(user_msg):
                return resolve_context_reply(user_msg)
            # Do not short-circuit improve requests into a lecture — gateway
            # routes those to the growth agent which actually acts.
        except Exception:
            pass

        # Normalize output for chat/greet modes
        so = dict(system_output or {})
        intent = (so.get("intent") or so.get("mode") or "").lower()
        if intent in ("chat", "greet") and "mode" not in so:
            so["mode"] = "greet" if intent == "greet" else "chat"
        if history and "history" not in so:
            # backends read history from the explicit kwarg, not so
            pass

        if not _TELEGRAM_LLM:
            return _format_fallback(so, user_msg)

        cache_key = None
        try:
            cache_key = self._cache_key(so, user_msg, history)
            cached = self._get_cached(cache_key)
            if cached is not None:
                logger.info("llm cache=hit prompt=%s", cache_key)
                return cached
            neg = self._get_negative(cache_key)
            if neg:
                logger.info("llm negative-cache=skip prompt=%s", cache_key)
                return _format_fallback(so, user_msg)
        except Exception:
            cache_key = None

        errors = []
        logger.info("llm routing policy primary=%s fallbacks=%s", self._primary, self._fallbacks)

        backends_map = self._backends()
        order = ordered_names(self._primary, ",".join(self._fallbacks))
        order = [b for b in order if b in backends_map]

        # best-effort candidate outputs to suppress low-value fallbacks
        cached_fallback = None
        fallback_quality = None

        for name in order:
            backend = backends_map[name]
            if not backend.available():
                continue
            try:
                out = backend.respond(so, user_msg, history=history)
            except TypeError:
                # Older backends without history kwarg
                try:
                    out = backend.respond(so, user_msg)
                except Exception as e:
                    msg = str(e)
                    logger.info("llm backend=%s skipped: %s", name, msg[:120])
                    self._mark_dead(backend, msg)
                    errors.append(f"{name}: {msg[:80]}")
                    continue
            except Exception as e:
                msg = str(e)
                logger.info("llm backend=%s skipped: %s", name, msg[:120])
                self._mark_dead(backend, msg)
                errors.append(f"{name}: {msg[:80]}")
                continue
            if out:
                logger.info("llm backend=%s response_len=%d", name, len(out))
                self._maybe_cache(cache_key, out, 2)
                return out
            if fallback_quality is None or 0 < fallback_quality:
                cached_fallback, fallback_quality = out, 0

        if errors:
            logger.warning("LLM reply failed, using fallback: %s", "; ".join(errors))
        logger.info("llm fallback: system_output=%s", so)
        if cached_fallback:
            self._maybe_cache(cache_key, cached_fallback, fallback_quality or 0)
            return cached_fallback
        return _format_fallback(so, user_msg)

    # ---- backends --------------------------------------------------------
    # (Concrete backends live in llm.backends.{openai,grok,ollama}.)

    # ---- HTTP ------------------------------------------------------------
    def _mark_dead(self, backend: Any, message: str) -> None:
        msg = message.lower()
        if "quota" in msg or "429" in msg:
            cooldown = 3600  # 1 hour
        elif "auth" in msg or "401" in msg or "403" in msg:
            cooldown = 86400  # 24 hours
        else:
            cooldown = 300  # 5 minutes
        from llm.backends.base import mark_dead as _mark
        name = getattr(backend, "name", "?")
        _mark(name, message, cooldown)
        logger.warning("LLM backend %s marked dead for %ds: %s", name, cooldown, message[:100])

    # ---- helpers ----------------------------------------------------------
    def _try_backend(self, backend: str, fn):  # type: ignore[return]
        try:
            out = fn()
            if out:
                logger.info("llm backend=%s response_len=%d", backend, len(out))
                return out, 2
            return "", 0
        except Exception as e:
            msg = str(e)
            logger.info("llm backend=%s skipped: %s", backend, msg[:120])
            self._mark_dead(backend, msg)
            return None, 1

    def _cache_key(
        self,
        system_output: Dict[str, Any],
        user_msg: str,
        history: Optional[Sequence[Dict[str, str]]] = None,
    ) -> str:
        hist_tail = ""
        if history:
            tail = list(history)[-4:]
            hist_tail = json.dumps(tail, sort_keys=True, default=str)[:800]
        payload = json.dumps(
            {"system_output": system_output, "user_msg": user_msg, "hist": hist_tail},
            sort_keys=True,
            default=str,
        )
        mark = hashlib.md5(payload.encode()).hexdigest()
        backend = self._primary or (self._fallbacks[0] if self._fallbacks else "ollama")
        return f"{backend}:default:{mark}"

    def _get_cached(self, key: Optional[str]) -> Optional[str]:  # type: ignore[return]
        if not key:
            return None
        entry = self._cache.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.time() - ts > self._cache_ttl:
            self._cache.pop(key, None)
            return None
        return value

    def _get_negative(self, key: Optional[str]) -> bool:  # type: ignore[return]
        if not key:
            return False
        ts = self._negative_cache.get(key)
        if not ts:
            return False
        if time.time() > ts:
            self._negative_cache.pop(key, None)
            return False
        return True

    def _maybe_cache(self, key: Optional[str], value: str, quality: int) -> None:
        if not key or not value:
            return
        if quality < 1:
            self._negative_cache[key] = time.time() + self._negative_ttl
            self._cache.pop(key, None)
            return
        if key in self._cache:
            self._cache[key] = (time.time(), value)
            return
        while len(self._cache) >= self._cache_max:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            self._cache.pop(oldest, None)
        self._cache[key] = (time.time(), value)


# --- Local fallback (always works) ---------------------------------------

def _local_classify(text: str) -> Dict[str, Any]:
    t = text.strip().lower()
    if not t:
        return {"intent": "chat", "confidence": "0.2"}
    for intent, pat, conf in [
        ("scan", r"\b(?:scan|nmap|port)\b", 0.85),
        ("greet", r"^(?:hi|hello|hey|sup|yo|alive|howdy|hiya)\b", 0.95),
    ]:
        if re.search(pat, t):
            return {"intent": intent, "confidence": str(conf)}
    return {"intent": "chat", "confidence": "0.4"}


def _format_fallback(system_output: Dict[str, Any], user_msg: str = "") -> str:
    if not isinstance(system_output, dict):
        return str(system_output)
    intent = (system_output.get("intent") or system_output.get("mode") or "respond").lower()
    action = system_output.get("action", "")
    agent = system_output.get("agent") or system_output.get("tile") or ""
    status = system_output.get("status", "")
    summary = (
        system_output.get("formatted")
        or system_output.get("summary")
        or system_output.get("result")
        or system_output.get("message")
        or ""
    )
    name = system_output.get("user_name")
    hi = f"Hey{(' ' + name) if name else ''}."

    if intent in ("greet",) or system_output.get("mode") == "greet":
        return (
            f"{hi} I'm Prometheous — just talk to me like a person. "
            "What are you working on?"
        )
    if intent == "chat" or system_output.get("mode") == "chat":
        # Stay present even without an LLM
        lower = (user_msg or "").lower()
        if re.search(r"\b(?:thanks|thank you|thx|ty)\b", lower):
            return "Anytime. What next?"
        if re.search(r"\b(?:how are you|how's it going)\b", lower):
            return "I'm good — online and ready. What's on your mind?"
        if "?" in (user_msg or ""):
            return (
                "Good question. I can dig into that, pull research, write something up, "
                "or just think it through with you — what do you want?"
            )
        return "I'm here. Tell me more, or just say what you want done."
    if intent == "commands" or system_output.get("commands"):
        try:
            from swarm.commands import format_commands_text
            return format_commands_text()
        except Exception:
            return "Just tell me what you need in plain language — no special commands required."
    if intent == "identity" or system_output.get("identity"):
        return system_output.get("message") or (
            "I'm Prometheous. Not a single chatbot model — I route work to specialists "
            "and actually execute. Just talk normally; I'll figure out the rest."
        )
    if intent == "scan" and action == "dispatch" and agent:
        return f"On it — spinning up a scan now."
    if action == "dispatch" and agent:
        if summary:
            return str(summary)
        return f"Working on that for you now."
    if summary:
        return str(summary)
    if intent and intent not in ("respond", "dispatch"):
        return f"Got it — {intent.replace('_', ' ')}."
    return "Got it. What would you like me to do with that?"


# Single shared instance
llm = LLMClient()
