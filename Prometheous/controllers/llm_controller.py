"""
LLM controller — wraps prometheus.llm.controller for agent use.
"""
import subprocess
from prometheus.llm.controller import LLMController


class AgentLLM:
    """Agent-facing LLM interface. Delegates to Prometheus LLM."""

    def __init__(self):
        self._controller = LLMController()

    def call(self, prompt: str, temperature: float = 0.3) -> str:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're in an async context — use the controller directly
            import sys
            import json

            # Try Claude API via controller's own aiohttp
            api_key = self._controller.api_key
            if api_key:
                try:
                    import aiohttp
                    async def _do_call():
                        async with aiohttp.ClientSession() as session:
                            async with session.post(
                                "https://api.anthropic.com/v1/messages",
                                headers={
                                    "x-api-key": api_key,
                                    "anthropic-version": "2023-06-01",
                                    "content-type": "application/json"
                                },
                                json={
                                    "model": self._controller.model,
                                    "max_tokens": 4096,
                                    "temperature": temperature,
                                    "messages": [{"role": "user", "content": prompt}]
                                }
                            ) as resp:
                                data = await resp.json()
                                return data["content"][0]["text"]
                    return loop.run_until_complete(_do_call())
                except Exception:
                    pass

            # Fallback: Ollama subprocess
            try:
                result = subprocess.run(
                    ["ollama", "run", "llama3.2", prompt.strip()],
                    capture_output=True, text=True, timeout=60
                )
                return result.stdout.strip()
            except Exception as e:
                return f"Error: {e}"
        else:
            # No running loop — use sync path
            import subprocess
            try:
                result = subprocess.run(
                    ["ollama", "run", "llama3.2", prompt.strip()],
                    capture_output=True, text=True, timeout=60
                )
                return result.stdout.strip()
            except Exception as e:
                return f"Error: {e}"


llm = AgentLLM()