"""
Conversational message building for Prometheous.

Turns cold system-output dumps into something that feels like talking
to a capable person who remembers the thread.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence


# Strong signals the user wants work done (not small talk / Q&A).
_WORK_SIGNALS = re.compile(
    r"(?:"
    r"\b(?:write|create|build|make|generate|deploy|implement|scaffold|fix)\b.+\b|"
    r"\b(?:run|execute|launch|publish|install|compile)\b|"
    r"\b(?:scan|nmap|port\s*scan)\b|"
    r"\b(?:search\s+(?:the\s+)?web|look\s+up|google)\b|"
    r"\b(?:read|open|show|list)\s+(?:file|folder|dir|path|main\.py|requirements)\b|"
    r"\b(?:fetch|download)\s+https?://|"
    r"\b(?:save|write)\s+(?:to|as|into)\b|"
    r"\b(?:ad\s*campaign|shopify|meta\s+ads)\b|"
    r"\b(?:self[- ]?(?:grow|improve|audit)|grow\s+yourself|learn\s+from\s+github)\b|"
    r"\b(?:mission|mosaic|polymorphic)\b|"
    r"\b(?:create\s+skill|run\s+skill)\b|"
    r"^(?:/[\w]+)"
    r")",
    re.I,
)

# Pure conversation / advice / small talk — should NOT spin up the task agent.
_CHATTY = re.compile(
    r"(?:"
    r"^(?:hi|hello|hey|sup|yo|howdy|hiya|good\s+(?:morning|afternoon|evening)|what's\s+up|whats\s+up)[\s!.?]*$|"
    r"\b(?:how are you|how's it going|hows it going|you good|you there)\b|"
    r"\b(?:thanks|thank you|thx|ty|appreciate it)\b|"
    r"\b(?:what do you think|your opinion|can we talk|let's chat|lets chat)\b|"
    r"\b(?:i(?:'m| am) (?:bored|lonely|stressed|confused|stuck))\b|"
    r"\b(?:tell me (?:a )?(?:joke|story)|be honest|just curious)\b"
    r")",
    re.I,
)

# Short follow-ups that need history context.
_FOLLOWUP = re.compile(
    r"^(?:"
    r"why\??|how\??|and\??|so\??|really\??|ok(?:ay)?|sure|yes|no|yep|nope|"
    r"go on|continue|more|what about (?:that|it)|same|again|please|"
    r"that one|the first|the second|do it|sounds good|wait|"
    r"what\??|huh\??|hmm+\??|lol|lmao|haha+"
    r")[\s!.?]*$",
    re.I,
)


def looks_like_work(text: str) -> bool:
    """True when the message is an actionable task, not conversation."""
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("/"):
        return True
    if _CHATTY.search(t) and not _WORK_SIGNALS.search(t):
        return False
    if _FOLLOWUP.match(t):
        return False
    return bool(_WORK_SIGNALS.search(t))


def looks_like_conversation(text: str) -> bool:
    """True for small talk, opinions, short follow-ups — talk, don't task."""
    t = (text or "").strip()
    if not t:
        return True
    if looks_like_work(t):
        return False
    if _CHATTY.search(t) or _FOLLOWUP.match(t):
        return True
    # Short messages without imperative work verbs → conversation
    words = t.split()
    if len(words) <= 12 and not re.search(
        r"\b(?:write|create|build|make|deploy|scan|run|execute|fetch|install)\b",
        t,
        re.I,
    ):
        return True
    # Questions that seek understanding, not artifacts
    if t.endswith("?") and not re.search(
        r"\b(?:can you (?:write|build|create|make|run|scan|search)|please (?:write|build|create))\b",
        t,
        re.I,
    ):
        return True
    return False


def truncate_history(
    history: Optional[Sequence[Dict[str, str]]],
    *,
    limit: int = 12,
    max_chars: int = 1800,
) -> List[Dict[str, str]]:
    """Keep recent user/assistant turns, trimmed for token budget."""
    if not history:
        return []
    out: List[Dict[str, str]] = []
    for turn in list(history)[-limit:]:
        role = (turn.get("role") or "").strip()
        content = (turn.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if len(content) > max_chars:
            content = content[: max_chars - 20] + "\n…(truncated)"
        out.append({"role": role, "content": content})
    return out


def build_messages(
    system_prompt: str,
    user_msg: str,
    system_output: Optional[Dict[str, Any]] = None,
    history: Optional[Sequence[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """
    Build chat-completions messages.

    Modes (via system_output.mode or inferred):
      - chat: pure conversation — user text as-is, with history
      - phrase: turn work results into a natural spoken reply
    """
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for turn in truncate_history(history):
        messages.append(turn)

    mode = "chat"
    so = system_output if isinstance(system_output, dict) else {}
    if so.get("mode") in ("chat", "phrase", "greet"):
        mode = str(so["mode"])
    elif so and so.get("intent") not in (None, "chat", "greet", "respond", ""):
        mode = "phrase"
    elif so and (so.get("result") is not None or so.get("status") or so.get("agent")):
        mode = "phrase"
    elif so.get("intent") in ("greet", "chat"):
        mode = "chat" if so.get("intent") != "greet" else "greet"

    if mode in ("chat", "greet"):
        # Speak like a person; optional light context only
        user_content = (user_msg or "").strip()
        if mode == "greet" and not user_content:
            user_content = "hello"
        # If we have soft context (name, last topic), append as a whisper
        whisper = _soft_context(so)
        if whisper:
            user_content = f"{user_content}\n\n(context for you only — don't recite: {whisper})"
        messages.append({"role": "user", "content": user_content})
        return messages

    # Phrase mode: natural report of work already done
    payload = {
        "what_the_user_said": user_msg,
        "what_happened": _compact_output(so),
    }
    instruction = (
        "The system already acted. Reply as yourself — a real person talking. "
        "Tell them what you did, what you found, or where things landed. "
        "No JSON, no 'as an AI', no fake slash-command menus. "
        "If something failed, say so plainly and what still worked.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)[:3500]}"
    )
    messages.append({"role": "user", "content": instruction})
    return messages


def _soft_context(so: Dict[str, Any]) -> str:
    bits: List[str] = []
    if so.get("user_name"):
        bits.append(f"their name is {so['user_name']}")
    if so.get("last_topic"):
        bits.append(f"last topic: {so['last_topic']}")
    if so.get("context"):
        bits.append(str(so["context"])[:400])
    return "; ".join(bits)


def _compact_output(so: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only high-signal fields for phrasing."""
    keys = (
        "intent",
        "agent",
        "status",
        "summary",
        "result",
        "reason",
        "formatted",
        "error",
        "deliverables",
        "message",
    )
    out: Dict[str, Any] = {}
    for k in keys:
        if k in so and so[k] not in (None, "", [], {}):
            val = so[k]
            if isinstance(val, str) and len(val) > 2000:
                val = val[:2000] + "…"
            elif isinstance(val, (dict, list)):
                raw = json.dumps(val, default=str)
                if len(raw) > 2000:
                    val = raw[:2000] + "…"
            out[k] = val
    return out or so
