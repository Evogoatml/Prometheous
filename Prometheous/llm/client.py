
"""
Prometheous LLM client — pure I/O gateway.

This is the ONLY place that talks to an LLM API. The system never does
reasoning, planning, or decision-making through the LLM. The LLM is used
for two narrow things:

  1. PHRASE a response in natural language given structured system output.
  2. CLASSIFY free-form text into a small set of intents (the orchestrator
     uses the result, but the LLM is never the decider).

If the LLM is unavailable (no key, no network), the gateway falls back
to a deterministic local intent parser and returns the raw system
output as the response.
"""
import json
import logging
import os
import re
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Intent vocabulary used everywhere ---------------------------------------
ALLOWED_INTENTS = {
    "scan", "recon", "exploit", "privesc", "persist", "pivot",
    "exfil", "report", "create_skill", "run_skill", "chat", "greet",
}

INTENT_LABELS = {
    "scan":         "Run a vulnerability / port scan",
    "recon":        "Reconnaissance / enumeration",
    "exploit":      "Exploitation",
    "privesc":      "Privilege escalation",
    "persist":      "Establish persistence",
    "pivot":        "Lateral movement / pivot",
    "exfil":        "Exfiltrate data",
    "report":       "Generate a report",
    "create_skill": "Create a new skill",
    "run_skill":    "Run a named skill",
    "chat":         "General chat (system will respond)",
    "greet":        "Greeting",
}


class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.model = os.getenv("PROM_LLM_MODEL", "llama3.2")
        self.timeout = int(os.getenv("PROM_LLM_TIMEOUT", "60"))
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self._anthropic_url = "https://api.anthropic.com/v1/messages"
        self._ollama_generate = self.ollama_url + "/api/generate"
        self._ollama_chat = self.ollama_url + "/api/chat"

    # ---- public API ---------------------------------------------------
    def classify_intent(self, text):
        """
        Return {"intent": "<one of ALLOWED_INTENTS>", "confidence": "0..1"}.
        Never call any LLM "decide" method — this is classification only.
        """
        if self.api_key:
            try:
                return self._anthropic_classify(text)
            except Exception as e:
                logger.warning("anthropic classify failed, falling back: %s", e)

        try:
            return self._ollama_classify(text)
        except Exception as e:
            logger.warning("ollama classify failed, falling back to local parser: %s", e)
            return _local_classify(text)

    def respond(self, system_output, user_msg):
        """
        Phrase a natural-language response from structured system output.
        The system did the work — the LLM is just the mouth, not the brain.
        """
        if self.api_key:
            try:
                return self._anthropic_respond(system_output, user_msg)
            except Exception as e:
                logger.warning("anthropic respond failed, falling back: %s", e)

        try:
            return self._ollama_respond(system_output, user_msg)
        except Exception as e:
            logger.warning("ollama respond failed, falling back to raw output: %s", e)

        return _format_fallback(system_output)

    # ---- anthropic backend --------------------------------------------
    def _anthropic_classify(self, text):
        intents = ", ".join(sorted(ALLOWED_INTENTS))
        prompt = (
            "You are a text classifier. Read the user input and pick EXACTLY one "
            "intent from this list: " + intents + ".\n"
            "Reply ONLY with JSON: {\"intent\": \"<intent>\", \"confidence\": \"<0-1>\"}.\n\n"
            "User input: \"" + text + "\""
        )
        body = json.dumps({
            "model": self.model,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            self._anthropic_url,
            data=body,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode())
        text_out = "".join(b.get("text", "") for b in payload.get("content", []))
        return _parse_intent_json(text_out, default_text=text)

    def _anthropic_respond(self, system_output, user_msg):
        body = json.dumps({
            "model": self.model,
            "max_tokens": 600,
            "system": (
                "You are a thin I/O layer for an agent system. The system has ALREADY "
                "decided everything: intent, agent, action, result. Your only job is "
                "to phrase the system's structured output as a short, natural reply "
                "to the user. Do NOT invent new actions, agents, or decisions. If the "
                "system_output contains an 'error' or 'failed' status, surface that "
                "honestly. Keep replies under 400 words."
            ),
            "messages": [
                {"role": "user", "content": (
                    "User said: " + user_msg + "\n\n"
                    "System output: " + json.dumps(system_output, default=str) + "\n\n"
                    "Reply to the user."
                )}
            ],
        }).encode()
        req = urllib.request.Request(
            self._anthropic_url,
            data=body,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode())
        return "".join(b.get("text", "") for b in payload.get("content", []))

    # ---- ollama backend ----------------------------------------------
    def _ollama_classify(self, text):
        intents = ", ".join(sorted(ALLOWED_INTENTS))
        prompt = (
            "Classify the user input into EXACTLY one intent from: " + intents + ".\n"
            "Reply with JSON only: {\"intent\": \"<intent>\", \"confidence\": \"<0-1>\"}.\n\n"
            "Input: \"" + text + "\""
        )
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request(
            self._ollama_generate,
            data=body,
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode())
        return _parse_intent_json(payload.get("response", ""), default_text=text)

    def _ollama_respond(self, system_output, user_msg):
        body = json.dumps({
            "model": self.model,
            "stream": False,
            "system": (
                "You are a thin I/O layer for an agent system. The system has ALREADY "
                "decided everything: intent, agent, action, result. Your only job is "
                "to phrase the system's structured output as a short, natural reply "
                "to the user. Do NOT invent new actions, agents, or decisions."
            ),
            "messages": [
                {"role": "user", "content": (
                    "User said: " + user_msg + "\n\n"
                    "System output: " + json.dumps(system_output, default=str) + "\n\n"
                    "Reply to the user."
                )},
            ],
        }).encode()
        req = urllib.request.Request(
            self._ollama_chat,
            data=body,
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode())
        msg = payload.get("message") or {}
        return msg.get("content", "") or _format_fallback(system_output)


# --- Local fallback (NO LLM) -------------------------------------------

def _local_classify(text):
    """
    Deterministic keyword-based classifier. Used when no LLM is reachable.
    The system still does ALL the actual decision-making via DecisionEngine;
    this just narrows the field so the LLM (if/when online) is consistent.
    """
    t = text.strip().lower()
    if not t:
        return {"intent": "chat", "confidence": "0.2"}

    patterns = [
        ("create_skill", r"^create skill\s+",                 0.9),
        ("run_skill",    r"^(?:run|execute)\s+",               0.9),
        ("scan",         r"\b(?:scan|nmap|port)\b",            0.85),
        ("recon",        r"\b(?:recon|whois|enum\w*|dns)\b",   0.85),
        ("exploit",      r"\b(?:exploit|attack|pwn)\b",        0.85),
        ("privesc",      r"\b(?:priv\w*\s*esc|escalat\w+|sudo)\b", 0.85),
        ("persist",      r"\b(?:persist\w*|backdoor)\b",       0.8),
        ("pivot",        r"\b(?:pivot|lateral)\b",             0.8),
        ("exfil",        r"\b(?:exfil\w*)\b",                  0.8),
        ("report",       r"\b(?:report|summary|markdown)\b",   0.7),
        ("greet",        r"^(?:hi|hello|hey|sup|yo|alive)\b",  0.95),
    ]
    for intent, pat, conf in patterns:
        if re.search(pat, t):
            return {"intent": intent, "confidence": str(conf)}
    return {"intent": "chat", "confidence": "0.4"}


def _parse_intent_json(raw, default_text):
    """Extract {"intent": "...", "confidence": "..."} from LLM text. Fall back to local."""
    m = re.search(r"\{.*?\}", raw, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            intent = str(obj.get("intent", "")).strip().lower()
            if intent in ALLOWED_INTENTS:
                conf = str(obj.get("confidence", "0.5"))
                return {"intent": intent, "confidence": conf}
        except (json.JSONDecodeError, ValueError):
            pass
    return _local_classify(default_text)


def _format_fallback(system_output):
    """When even the LLM is gone: surface the system's structured output cleanly."""
    status = system_output.get("status", "ok")
    intent = system_output.get("intent", "respond")
    agent = system_output.get("agent")
    summary = system_output.get("summary") or system_output.get("result") or system_output

    lines = ["Status: " + str(status), "Intent: " + str(intent)]
    if agent:
        lines.append("Agent: " + str(agent))
    if summary and summary != system_output:
        lines.append("Detail: " + json.dumps(summary, default=str)[:600])
    return "\n".join(lines)


# Single shared instance
llm = LLMClient()
