# prometheus/llm/controller.py
import os
import json
import subprocess
from typing import Dict, Any


class LLMController:
    """One LLM gateway.

    Responds to prompts and classifies intent; **never** decides what the
    system should do.
    """

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")

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
                            "model": self.model,
                            "max_tokens": 4096,
                            "temperature": temperature,
                            "messages": [{"role": "user", "content": prompt}]
                        }
                    ) as resp:
                        data = await resp.json()
                        return data["content"][0]["text"]
            except Exception as e:
                print(f"Claude API error: {e}")

        # Fallback: Ollama
        try:
            result = subprocess.run(
                ["ollama", "run", "llama3.2", prompt],
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.stdout.strip()
        except Exception as e:
            return f"Error: {e}"
