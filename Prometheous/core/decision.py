"""
System-side decision engine.

Takes an intent (parsed from user input by the LLM gateway OR by the intent
parser) and a context, then decides:
  1. Which agent to dispatch to (if any)
  2. Whether to ask the LLM for a response
  3. Whether to write to memory

Rule-based + intent matching. NO LLM call from inside here.
The LLM is purely a translator in/out; the system decides.
"""
import re
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    action: str               # "dispatch" | "respond" | "create_skill" | "run_skill" | "reflect"
    agent: Optional[str] = None
    target: Optional[str] = None
    skill_name: Optional[str] = None
    reason: str = ""
    confidence: float = 0.5


# Keyword → intent map. Order matters: more specific patterns first.
INTENT_PATTERNS: List[Tuple[str, re.Pattern, str, str]] = [
    # (intent_name, regex, default_agent, description)
    ("create_skill", re.compile(r"^create skill\s+(.+)$", re.I), "skill_builder", "create a new skill"),
    ("run_skill",    re.compile(r"^(?:run|execute)\s+(.+)$", re.I), "executor",  "run a named skill"),
    ("scan",         re.compile(r"\b(?:scan|nmap|port\s*scan)\b", re.I), "scanner",  "vulnerability scan"),
    ("recon",        re.compile(r"\b(?:recon|whois|dns|enum(?:erate)?)\b", re.I), "recon", "reconnaissance"),
    ("exploit",      re.compile(r"\b(?:exploit|attack|pwn|hack)\b", re.I), "exploit", "exploitation"),
    ("privesc",      re.compile(r"\b(?:priv(?:ilege)?\s*esc|escalat\w+|sudo|kernel)\b", re.I), "privesc", "privilege escalation"),
    ("persist",      re.compile(r"\b(?:persist\w*|backdoor|rootkit|schedule)\b", re.I), "persist", "persistence"),
    ("pivot",        re.compile(r"\b(?:pivot|lateral|psexec|ssh\.|wmiconv)\b", re.I), "pivot", "lateral movement"),
    ("exfil",        re.compile(r"\b(?:exfil\w*|upload|exfiltrate)\b", re.I), "exfil", "data exfiltration"),
    ("report",       re.compile(r"\b(?:report|markdown|summary)\b", re.I), "report", "reporting"),
    ("greet",        re.compile(r"^(?:hi|hello|hey|alive|sup|yo)\b", re.I), None, "greeting"),
    ("chat",         re.compile(r".+", re.I), None, "general chat"),  # catch-all
]


class DecisionEngine:
    """Picks an action from a user message. No LLM."""

    def __init__(self):
        self.history: List[Decision] = []
        self.max_history = 100

    def decide(self, message: str, context: Optional[Dict[str, Any]] = None) -> Decision:
        ctx = context or {}
        text = message.strip()
        lower = text.lower()

        for intent_name, pattern, agent, desc in INTENT_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue

            # Build the decision
            reason = f"matched intent '{intent_name}' ({desc})"
            confidence = 0.9 if intent_name in ("scan", "recon", "exploit", "create_skill", "run_skill") else 0.7

            if intent_name == "create_skill":
                skill = m.group(1).strip().replace(" ", "_")
                return self._record(Decision(
                    action="create_skill",
                    skill_name=skill,
                    reason=reason,
                    confidence=confidence,
                ))

            if intent_name == "run_skill":
                skill = m.group(1).strip().replace(" ", "_")
                return self._record(Decision(
                    action="run_skill",
                    skill_name=skill,
                    reason=reason,
                    confidence=confidence,
                ))

            if intent_name in ("greet", "chat"):
                return self._record(Decision(
                    action="respond",
                    reason=reason,
                    confidence=confidence,
                ))

            # dispatchable intent
            return self._record(Decision(
                action="dispatch",
                agent=agent,
                target=ctx.get("target"),
                reason=reason,
                confidence=confidence,
            ))

        # shouldn't reach (chat catch-all), but stay safe
        return self._record(Decision(action="respond", reason="no match", confidence=0.3))

    def _record(self, d: Decision) -> Decision:
        self.history.append(d)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]
        logger.info("decision: %s (conf=%.2f) — %s", d.action, d.confidence, d.reason)
        return d


# Single shared instance
engine = DecisionEngine()
