"""
Simple continual-learning strategy: experience replay buffer + metrics.

Phase 1. Swap via LearningStrategy ABC later (meta-learning, EWC, …).
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List

from ..core.interfaces import LearningStrategy


class ReplayLearningStrategy(LearningStrategy):
    name = "replay"
    version = "1.0.0"

    def __init__(self, capacity: int = 256):
        self.capacity = capacity
        self.buffer: Deque[Dict[str, Any]] = deque(maxlen=capacity)
        self.success_count = 0
        self.fail_count = 0
        self.rounds = 0

    def observe(self, experience: Dict[str, Any]) -> None:
        self.buffer.append(dict(experience))
        if experience.get("success"):
            self.success_count += 1
        else:
            self.fail_count += 1

    def improve(self) -> Dict[str, Any]:
        self.rounds += 1
        total = max(self.success_count + self.fail_count, 1)
        # Phase 1 "learning": surface failure modes for routing bias later
        failures = [e for e in self.buffer if not e.get("success")][-10:]
        failure_agents: Dict[str, int] = {}
        for e in failures:
            a = str(e.get("agent") or "?")
            failure_agents[a] = failure_agents.get(a, 0) + 1
        return {
            "strategy": self.name,
            "rounds": self.rounds,
            "buffer_size": len(self.buffer),
            "success_rate": self.success_count / total,
            "failure_agents": failure_agents,
            "last_failures": [
                {"goal": f.get("goal"), "error": f.get("error")} for f in failures[-3:]
            ],
        }

    def status(self) -> Dict[str, Any]:
        base = super().status()
        base.update(
            {
                "buffer_size": len(self.buffer),
                "success_count": self.success_count,
                "fail_count": self.fail_count,
            }
        )
        return base
