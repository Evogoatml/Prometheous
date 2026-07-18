"""
Mission agent — user-facing plan → code → deploy → execute.
"""
from __future__ import annotations

from typing import Any, Dict

from core.mission import get_conductor


class MissionAgent:
    name = "mission"
    role = "MissionConductor"
    specialty = "plan task → write code → deploy agents → execute until done"
    tasks_completed = 0

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        goal = ""
        for k in ("goal", "query", "target", "user_msg", "text", "task"):
            if payload.get(k):
                goal = str(payload[k]).strip()
                break
        # strip slash command prefix if present
        for prefix in ("/mission", "/do", "/run mission", "mission"):
            if goal.lower().startswith(prefix):
                goal = goal[len(prefix) :].strip(" :-\t")
                break
        result = get_conductor().run(goal, payload)
        return result.to_agent_result()
