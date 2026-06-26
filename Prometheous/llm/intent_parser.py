
"""
Local intent parser. Pure string → intent. No LLM, no external calls.

Used by the LLM gateway as a fallback when no LLM is reachable, and by
the decision engine as a sanity check on LLM classification results.
The system NEVER trusts the LLM's classification unconditionally — it
verifies the returned intent is in the allowed vocabulary.
"""
import re
from typing import Any, Dict


ALLOWED_INTENTS = {
    "scan", "recon", "exploit", "privesc", "persist", "pivot",
    "exfil", "report", "create_skill", "run_skill", "chat", "greet",
}


def interpret_command(user_input: str) -> Dict[str, Any]:
    """
    Analyze user text and return a structured plan with intent + steps.
    System-side only — the LLM gateway is NOT consulted.
    """
    text = (user_input or "").strip()
    lower = text.lower()

    # create skill <name>
    if lower.startswith("create skill"):
        skill_name = re.sub(r"^create skill\s+", "", text, flags=re.I).strip().replace(" ", "_")
        return {
            "intent": "create_skill",
            "confidence": 0.95,
            "steps": [
                {"action": "create_skill", "description": "Create new skill", "skill_name": skill_name}
            ],
        }

    # run <name> | execute <name>
    if lower.startswith("run ") or lower.startswith("execute "):
        skill_name = re.sub(r"^(run|execute)\s+", "", text, flags=re.I).strip().replace(" ", "_")
        return {
            "intent": "run_skill",
            "confidence": 0.95,
            "steps": [
                {"action": "run_skill", "description": "Run skill", "skill_name": skill_name}
            ],
        }

    # keyword routing
    keyword_map = [
        ("scan",      r"\b(?:scan|nmap|port\s*scan)\b"),
        ("recon",     r"\b(?:recon|whois|enum\w*|dns)\b"),
        ("exploit",   r"\b(?:exploit|attack|pwn|hack)\b"),
        ("privesc",   r"\b(?:priv(?:ilege)?\s*esc|escalat\w+|sudo|kernel)\b"),
        ("persist",   r"\b(?:persist\w*|backdoor|rootkit)\b"),
        ("pivot",     r"\b(?:pivot|lateral)\b"),
        ("exfil",     r"\b(?:exfil\w*|exfiltrate|upload)\b"),
        ("report",    r"\b(?:report|markdown|summary)\b"),
        ("greet",     r"^(?:hi|hello|hey|alive|sup|yo)\b"),
    ]
    for intent, pat in keyword_map:
        if re.search(pat, lower):
            return {
                "intent": intent,
                "confidence": 0.85,
                "steps": [
                    {"action": "dispatch", "description": "Dispatch to specialist", "agent": intent}
                ],
            }

    # chat fallback
    return {
        "intent": "chat",
        "confidence": 0.4,
        "steps": [
            {"action": "respond", "description": "Free-form response from LLM gateway"},
        ],
    }


def is_allowed(intent: str) -> bool:
    return intent in ALLOWED_INTENTS
