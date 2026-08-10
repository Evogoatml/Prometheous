"""
LLM controller — thin wrapper for Prometheous LLM.
Uses the main llm.client or local llm/controller.
"""
import subprocess
from llm.model_resolver import resolve_backend_model
from utils.config import cfg
# Use the project's llm controller if present, else fallback to client
try:
    from llm.controller import LLMController
except ImportError:
    from llm.client import llm as LLMController  # fallback shape


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
                                    "model": resolve_backend_model("anthropic", getattr(self._controller, "model", "")),
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
                    ["ollama", "run", resolve_backend_model("ollama", getattr(self._controller, "model", "")), prompt.strip()],
                    capture_output=True, text=True, timeout=cfg.LLM_TIMEOUT
                )
                return result.stdout.strip()
            except Exception as e:
                return f"Error: {e}"
        else:
            # No running loop — use sync path
            import subprocess
            try:
                result = subprocess.run(
                    ["ollama", "run", resolve_backend_model("ollama", getattr(self._controller, "model", "")), prompt.strip()],
                    capture_output=True, text=True, timeout=cfg.LLM_TIMEOUT
                )
                return result.stdout.strip()
            except Exception as e:
                return f"Error: {e}"


llm = AgentLLM()