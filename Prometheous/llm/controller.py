# prometheus/llm/controller.py
import os
import json
import subprocess
from typing import Dict, Any

from llm.model_resolver import resolve_backend_model


class LLMController:
    """One LLM gateway.

    Responds to prompts and classifies intent; **never** decides what the
    system should do.
    """

    def __init__(self, model: str = ""):
        self.model = model
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.grok_api_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY", "")

    async def call(self, prompt: str, temperature: float = 0.3) -> str:
        # Try Claude API
        if self.api_key:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": self.api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json"
                        },
                        json={
                            "model": resolve_backend_model("anthropic", self.model),
                            "max_tokens": 4096,
                            "temperature": temperature,
                            "messages": [{"role": "user", "content": prompt}]
                        }
                    ) as resp:
                        data = await resp.json()
                        return data["content"][0]["text"]
            except Exception as e:
                print(f"Claude API error: {e}")

        # Try Grok API (xAI, OpenAI compatible)
        if self.grok_api_key:
            try:
                import urllib.request
                import json
                body = json.dumps({
                    "model": resolve_backend_model("grok", self.model),
                    "max_tokens": 4096,
                    "temperature": temperature,
                    "messages": [{"role": "user", "content": prompt}]
                }).encode()
                req = urllib.request.Request(
                    "https://api.x.ai/v1/chat/completions",
                    data=body,
                    headers={
                        "Authorization": f"Bearer {self.grok_api_key}",
                        "Content-Type": "application/json"
                    }
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode())
                    return data["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"Grok API error: {e}")

        # Fallback: Ollama
        try:
            result = subprocess.run(
                ["ollama", "run", resolve_backend_model("ollama", self.model), prompt],
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.stdout.strip()
        except Exception as e:
            return f"Error: {e}"
