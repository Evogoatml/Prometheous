"""Ollama local chat-completions backend (http://localhost:11434)."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Sequence

from llm.backends.base import Backend, is_live, cooldown_remaining
from utils.config import cfg

logger = logging.getLogger(__name__)


class OllamaBackend(Backend):
    name = "ollama"

    def __init__(self, url: str = "", model: str = "", timeout: int = 30):
        self.url = (url or cfg.OLLAMA_URL).rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        return is_live(self.name)

    def cooldown_seconds_remaining(self) -> float:
        return cooldown_remaining(self.name)

    def respond(
        self,
        system_output: Dict[str, Any],
        user_msg: str,
        *,
        history: Optional[Sequence[Dict[str, str]]] = None,
    ) -> str:
        from llm.client import PROMETHEOUS_SYSTEM_PROMPT
        from llm.conversation import build_messages

        model = self.model or cfg.LLM_MODEL
        messages = build_messages(
            PROMETHEOUS_SYSTEM_PROMPT,
            user_msg,
            system_output=system_output,
            history=history,
        )
        body = json.dumps({
            "model": model,
            "stream": False,
            "options": {
                "temperature": 0.7 if (system_output or {}).get("mode") in ("chat", "greet") else 0.4,
            },
            "messages": messages,
        }).encode()
        req = urllib.request.Request(self.url + "/api/chat", data=body, headers={"content-type": "application/json"})
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = resp.read()
                payload = json.loads(data.decode())
                return payload.get("message", {}).get("content", "") or ""
            except urllib.error.HTTPError as e:
                err = e.read().decode() if hasattr(e, "read") else str(e)
                raise RuntimeError(f"HTTP {e.code}: {err[:200]}") from e
            except Exception as e:
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise RuntimeError(str(e)) from e
        raise RuntimeError("request failed")
