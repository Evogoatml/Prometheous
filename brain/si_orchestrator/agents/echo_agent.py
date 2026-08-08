"""Minimal agent for tests / fallback."""

from __future__ import annotations

from typing import Sequence

from ..core.interfaces import Agent, AgentResult, AgentTask


class EchoAgent(Agent):
    name = "echo"
    version = "1.0.0"
    skills: Sequence[str] = ("echo", "test")

    def run(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.id,
            success=True,
            output=f"echo: {task.goal}",
            traces=[{"step": "echo"}],
        )
