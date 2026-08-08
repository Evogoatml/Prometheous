"""
Growth tile: learn a user-specified topic.

Used by tiles.registry as growth_learning. Delegates to LearnAgent / curriculum.
"""
from __future__ import annotations

from typing import Any, Dict


def learn_topic(topic: str, **kwargs: Any) -> Dict[str, Any]:
    """Research and store a single topic. Entry point for mosaic/tiles."""
    from agents.learn_agent import LearnAgent

    agent = LearnAgent()
    payload = {"topic": str(topic or "").strip(), "mode": "learn", **kwargs}
    return agent.execute(payload)


class LearningTile:
    """Tile wrapper with execute(task) for registry compatibility."""

    name = "growth_learning"

    def execute(self, task: Any) -> Dict[str, Any]:
        if isinstance(task, dict):
            topic = (
                task.get("topic")
                or task.get("goal")
                or task.get("query")
                or task.get("user_msg")
                or task.get("target")
                or ""
            )
            return learn_topic(str(topic), **{k: v for k, v in task.items() if k not in ("topic",)})
        return learn_topic(str(task))

