"""
System facade — wires user input to the SI orchestrator.

Flow: user message → LLM translates → orchestrator executes → result
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_BRAIN = _ROOT / "brain"
_SI = _BRAIN / "si_orchestrator"
for p in (_ROOT, _BRAIN):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

logger = logging.getLogger("prometheous.system")

from llm.model_resolver import resolve_backend_model
from utils.config import cfg


class SystemConfig:
    llm_provider: str = "ollama"
    llm_model: str = ""
    ollama_base_url: str = cfg.OLLAMA_URL
    anthropic_api_key: str = ""
    log_level: str = "INFO"


def load_config() -> SystemConfig:
    config = SystemConfig()
    config.llm_provider = os.environ.get("LLM_PROVIDER", "ollama")
    config.llm_model = os.environ.get("PROM_LLM_MODEL") or os.environ.get("LLM_MODEL", "")
    config.ollama_base_url = os.environ.get("OLLAMA_BASE_URL") or cfg.OLLAMA_URL
    config.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    config.log_level = os.environ.get("LOG_LEVEL", "INFO")
    return config


def _setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("prometheous.system")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, level))
    return logger


async def _llm_call(prompt: str, system_prompt: str = "", config: Optional[SystemConfig] = None) -> str:
    config = config or load_config()

    if config.llm_provider == "ollama":
        return await _call_ollama(config, prompt, system_prompt)
    elif config.llm_provider == "anthropic":
        return await _call_anthropic(config, prompt, system_prompt)
    else:
        return await _call_ollama(config, prompt, system_prompt)


async def _call_ollama(config: SystemConfig, prompt: str, system_prompt: str) -> str:
    import urllib.request
    url = f"{config.ollama_base_url}/api/generate"
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    payload = json.dumps({
        "model": resolve_backend_model("ollama", config.llm_model),
        "prompt": full_prompt,
        "stream": False,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode()).get("response", "")


async def _call_anthropic(config: SystemConfig, prompt: str, system_prompt: str) -> str:
    import urllib.request
    url = "https://api.anthropic.com/v1/messages"
    body = json.dumps({
        "model": resolve_backend_model("anthropic", config.llm_model),
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "x-api-key": config.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode())
    return "".join(b.get("text", "") for b in payload.get("content", []))


class System:
    def __init__(self, config: Optional[SystemConfig] = None):
        self.config = config or load_config()
        self.logger = _setup_logging(self.config.log_level)
        self.orchestrator = None
        self._load_orchestrator()

    def _load_orchestrator(self):
        try:
            from si_orchestrator.bootstrap import build_orchestrator
            self.orchestrator = build_orchestrator(base_dir=_SI)
            self.logger.info("SI orchestrator loaded")
        except Exception as e:
            self.logger.warning("SI orchestrator failed to load: %s", e)
            self.orchestrator = None

    async def chat(
        self,
        *,
        message: str,
        user_id: int,
        username: str,
        history: List[Dict[str, str]],
    ) -> Dict[str, Any]:

        system_prompt = (
            "You are the brain of Prometheous. You translate user requests into "
            "orchestrator commands. The orchestrator has these agents:\n"
            "- prometheus: reasoning, planning, analysis, general tasks\n"
            "- tools: file search, read, list operations\n"
            "- executor: runs Python code and shell commands\n"
            "- navigator: system exploration (filesystem, processes, network, disk),\n"
            "            stateful shell session (cd persists), create scripts/tools\n\n"
            "Reply with JSON only:\n"
            '{"goal": "<task description for orchestrator>", '
            '"agent": "<agent name or null>", '
            '"code": "<optional python code to execute>", '
            '"command": "<optional shell command for navigator>"}\n\n'
            "If the user just wants to chat or ask a question, "
            "set goal to their question and agent to null, code to null.\n"
            "If the user wants code written and executed, include the code.\n"
            "If the user wants file operations, set agent to tools.\n"
            "If the user wants to explore the system, browse files, check "
            "processes/disk/network, or create scripts, set agent to navigator.\n"
            "For navigator, you can set 'command' to a direct shell command.\n"
            "Do not include any explanation outside the JSON."
        )

        history_text = ""
        if history:
            recent = history[-5:]
            history_text = "\n".join(f"User: {h['content']}" for h in recent) + "\n"

        prompt = f"{history_text}User: {message}" if history_text else message
        llm_response = await _llm_call(prompt, system_prompt, self.config)

        try:
            match = re.search(r"\{.*\}", llm_response, re.S)
            if match:
                parsed = json.loads(match.group(0))
            else:
                parsed = {"goal": message, "agent": None, "code": None}
        except (json.JSONDecodeError, ValueError):
            parsed = {"goal": message, "agent": None, "code": None}

        goal = parsed.get("goal", message)
        agent_override = parsed.get("agent")
        code = parsed.get("code")
        command = parsed.get("command", "")

        if not self.orchestrator:
            return {"text": "Orchestrator not available. Check logs."}

        if agent_override == "navigator" and command:
            result = self.orchestrator.run(
                goal,
                agent_name="navigator",
                context={"command": command, "source": "llm_generated"},
            )
        elif code:
            result = self.orchestrator.run(
                goal,
                agent_name="executor",
                context={"code": code, "source": "llm_generated"},
            )
        else:
            result = self.orchestrator.run(goal, agent_name=agent_override)

        if result.success:
            output = str(result.output)
        else:
            output = f"Failed: {result.error or 'unknown error'}"

        try:
            phrase_prompt = (
                f"User asked: {message}\n"
                f"System result: {output}\n\n"
                f"Reply to the user in plain language. Be concise."
            )
            phrased = await _llm_call(phrase_prompt, "You are a helpful assistant.", self.config)
            if phrased and not phrased.startswith("[Error"):
                output = phrased
        except Exception:
            pass

        return {"text": output}


system = System()
