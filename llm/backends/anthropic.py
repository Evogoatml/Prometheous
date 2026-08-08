"""Anthropic Messages API backend."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Sequence

from llm.backends.base import Backend, cooldown_remaining, is_live

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class AnthropicBackend(Backend):
    name = "anthropic"

    def __init__(self, api_key: str = "", model: str = "", timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        if not (self.api_key and self.model and self.model.lower().startswith("claude")):
            return False
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

        messages = build_messages(
            PROMETHEOUS_SYSTEM_PROMPT,
            user_msg,
            system_output=system_output,
            history=history,
        )
        system_prompt = ""
        if messages and messages[0].get("role") == "system":
            system_prompt = messages[0].get("content", "")
            messages = messages[1:]
        max_tokens = 700 if (system_output or {}).get("mode") in ("chat", "greet") else 500
        body = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_prompt or PROMETHEOUS_SYSTEM_PROMPT,
            "messages": messages,
            "temperature": 0.7 if (system_output or {}).get("mode") in ("chat", "greet") else 0.4,
        }).encode()
        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        return self._http(req)

    def _http(self, req: urllib.request.Request) -> str:
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode())
                return "".join(block.get("text", "") for block in payload.get("content", []))
            except urllib.error.HTTPError as e:
                err = e.read().decode() if hasattr(e, "read") else str(e)
                if e.code in (401, 403):
                    raise RuntimeError(f"auth failed: {err[:200]}") from e
                if e.code == 429 and "quota" in err.lower():
                    raise RuntimeError(f"quota: {err[:200]}") from e
                if attempt == 0 and e.code in (500, 502, 503, 504):
                    time.sleep(1)
                    continue
                raise RuntimeError(f"HTTP {e.code}: {err[:200]}") from e
            except Exception as e:
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise RuntimeError(str(e)) from e
        raise RuntimeError("request failed")
