"""
Prometheous learning stack — awareness, trajectories, optimizer.
"""
from learning.awareness import AwarenessCore
from learning.task_memory import TaskMemory
from learning.optimizer import Optimizer, profile
from learning.trajectory import record_task
from learning.curriculum import Curriculum, curriculum
from learning.healing import (
    apply_live,
    apply_worktree,
    handle_failure,
    healing_summary,
    list_proposals_brief,
    self_healing,
)

__all__ = [
    "AwarenessLearner",
    "AwarenessCore",
    "TaskMemory",
    "Optimizer",
    "profile",
    "record_task",
    "Curriculum",
    "curriculum",
    "handle_failure",
    "self_healing",
    "healing_summary",
    "apply_worktree",
    "apply_live",
    "list_proposals_brief",
]


class AwarenessLearner:
    """Unified facade for error-aware learning + self-optimization."""

    def __init__(self):
        self.awareness = AwarenessCore()
        self.tasks = TaskMemory()
        self.optimizer = Optimizer()

    def record_outcome(
        self,
        module: str,
        *,
        success: bool,
        error: str | None = None,
        latency: float | None = None,
        context: dict | None = None,
    ) -> None:
        result = "success" if success else "failure"
        self.awareness.record_experience(
            module, result, latency=latency, error=error, context=context
        )
        self.tasks.record(module, result, metrics={"duration": latency, **(context or {})})

    def introspect(self) -> dict:
        return {
            "concepts": self.awareness.get_concepts(),
            "modules": self.awareness.get_module_stats(),
            "errors": self.awareness.recent_errors(limit=10),
            "tasks": self.tasks.summarize_all(),
            "recommendations": self.optimizer.get_recommendations(),
            "tuning": self.optimizer.get_tuning(),
        }

    def auto_tune(self) -> dict:
        return self.optimizer.auto_tune()

    def analyze(self) -> dict:
        summary = self.optimizer.analyze_efficiency()
        recs = self.optimizer.generate_recommendations()
        return {"efficiency": summary, "recommendations": recs}


learner = AwarenessLearner()