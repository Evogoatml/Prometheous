"""Mosaic agent — entry point for polymorphic auto-mosaic execution."""
from __future__ import annotations

from typing import Any, Dict

from core.mosaic import get_mosaic


class MosaicAgent:
    name = "mosaic"
    role = "Mosaic"
    specialty = "polymorphic auto-mosaic agentic assembly"
    tasks_completed = 0

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        goal = ""
        for k in ("goal", "query", "target", "user_msg", "text"):
            if payload.get(k):
                goal = str(payload[k]).strip()
                break
        result = get_mosaic().run(goal, payload)
        return result.to_agent_result()
