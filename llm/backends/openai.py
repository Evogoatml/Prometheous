"""OpenAI chat-completions backend (api.openai.com)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Sequence

from llm.backends.base import Backend, is_live, cooldown_remaining
from utils.config import cfg

logger = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIBackend(Backend):
    name = "openai"

    def __init__(self, api_key: str = "", model: str = "", timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        if not (self.api_key and self.model):
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
        max_tokens = cfg.LLM_MAX_TOKENS_CHAT if (system_output or {}).get("mode") in ("chat", "greet") else cfg.LLM_MAX_TOKENS_TASK
        body = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0.7 if (system_output or {}).get("mode") in ("chat", "greet") else 0.4,
            "messages": messages,
        }).encode()
        req = urllib.request.Request(
            OPENAI_URL, data=body,
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
        )
        return self._http(req)

    def _http(self, req: urllib.request.Request) -> str:
        import time
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = resp.read()
                payload = json.loads(data.decode())
                msg = (payload.get("choices") or [{}])[0].get("message", {})
                return msg.get("content", "") or ""
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
