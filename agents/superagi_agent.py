#!/usr/bin/env python3
"""
SuperAGIAgent — goal decomposer tile.

Uses the local Ollama LLM (via `llm.client.LLMClient`) to break a high-level
task into a short list of subtasks and optional tool calls. Falls back to a
deterministic split on conjunctions if the LLM is unavailable.

Registered with `tiles.registry.TileRegistry` on import (key: "superagi").
"""
import json
import re
import urllib.request
from typing import Any, Dict, List, Optional

from swarm.base import BaseAgent
from swarm.orchestrator import orb

try:
    from llm.client import LLMClient
except Exception:
    LLMClient = None

from utils.config import cfg

OLLAMA_URL = cfg.OLLAMA_URL


class SuperAGIAgent(BaseAgent):
    name = "superagi"
    role = "Goal Decomposer"
    specialty = "Break a high-level task into executable subtasks"
    version = "0.2.0"

    def __init__(self):
        super().__init__()
        self._llm = LLMClient() if LLMClient else None

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        query = (
            payload.get("task")
            or payload.get("text")
            or payload.get("user_msg")
            or payload.get("goal")
            or payload.get("query")
            or ""
        ).strip()
        if not query:
            return {"status": "error", "agent": self.name, "error": "empty task"}

        subtasks = self._decompose(query)
        return {
            "status": "ok",
            "agent": self.name,
            "tile": "superagi",
            "original": query,
            "subtasks": subtasks,
            "count": len(subtasks),
            "message": f"SuperAGI decomposed into {len(subtasks)} subtasks",
            "formatted": (
                f"🧩 SuperAGI: {len(subtasks)} subtasks\n"
                + "\n".join(
                    f"  {s.get('step', i+1)}. [{s.get('agent', '?')}] {s.get('description', '')[:100]}"
                    for i, s in enumerate(subtasks[:15])
                )
            ),
        }

    # ------------------------------------------------------------------
    def _decompose(self, query: str) -> List[Dict[str, str]]:
        # Try LLM first via Ollama chat (matches the local llm/client.py gateway).
        if self._llm is not None:
            try:
                return self._llm_decompose(query)
            except Exception:
                pass
        return self._fallback_decompose(query)

    def _llm_decompose(self, query: str) -> List[Dict[str, str]]:
        """
        Ask the local Ollama instance for a JSON array of subtasks.
        Prompt is shaped exactly like the existing `llm/client.py` gateway.
        """
        system = (
            "You are a task decomposer. Return ONLY a JSON array of subtasks. "
            "Each element must be an object with keys: "
            '"step" (number), "description" (string), "agent" (string from: '
            "scan, recon, exploit, privesc, pivot, exfil, report). "
            "Example: [{\"step\":1,\"description\":\"enumerate target\",\"agent\":\"recon\"}]"
        )
        body = json.dumps({
            "model": getattr(self._llm, "model", "llama3.2"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": query},
            ],
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=body,
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=int(getattr(self._llm, "timeout", 60))) as resp:
            data = json.loads(resp.read().decode())

        msg = ""
        for b in data.get("message", {}).get("content", ""):
            if isinstance(b, dict):
                msg += b.get("text", "")
            else:
                msg += b

        try:
            parsed = json.loads(msg)
            if isinstance(parsed, list) and all(isinstance(x, dict) for x in parsed):
                out = []
                for step in parsed:
                    out.append({
                        "step": str(step.get("step", len(out) + 1)),
                        "description": str(step.get("description", step.get("tool", "unknown"))).strip(),
                        "agent": str(step.get("agent", "scan")).strip().lower(),
                    })
                return out
        except Exception:
            pass
        return self._fallback_decompose(query)

    def _fallback_decompose(self, query: str) -> List[Dict[str, str]]:
        parts = [p.strip() for p in re.split(r"(?i)\band\b|,|;|\n|\|", query) if p.strip()]
        mapping = {
            "scan": "scan", "vuln": "scan", "nmap": "scan", "cve": "scan",
            "recon": "recon", "enum": "recon", "whois": "recon", "dns": "recon",
            "exploit": "exploit", "pwn": "exploit", "shell": "exploit", "meta": "exploit",
            "privesc": "privesc", "sudo": "privesc", "root": "privesc",
            "pivot": "pivot", "lateral": "pivot", "ssh": "pivot",
            "exfil": "exfil", "upload": "exfil", "dns": "exfil",
            "report": "report", "markdown": "report", "html": "report", "json": "report",
        }
        out = []
        for i, part in enumerate(parts[:8], start=1):
            lower = part.lower()
            agent = next((mapping[k] for k in mapping if k in lower), "scan")
            out.append({"step": str(i), "description": part, "agent": agent})
        return out or [{"step": "1", "description": query, "agent": "scan"}]


orb.register(SuperAGIAgent())
