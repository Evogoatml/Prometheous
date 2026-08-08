"""
Learning Coordinator — orchestrates observe → improve → optional sleep consolidation.

Phase 1: replay strategy + hooks for EWC / meta-learning later.
Safety: simple alignment gate before consolidation (no silent self-mod of core).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from ..core.interfaces import LearningStrategy, MemoryBackend


class LearningCoordinator:
    """
    High-level learning service used by SIOrchestrator (or scheduled jobs).

    - observe(experience): feed strategy
    - step(): run improve()
    - sleep_cycle(): consolidate memory + improve (offline "rest")
    """

    def __init__(
        self,
        strategy: LearningStrategy,
        memory: Optional[MemoryBackend] = None,
        *,
        min_success_rate_for_consolidate: float = 0.0,
        alignment_checks: Optional[List[Callable[[Dict[str, Any]], bool]]] = None,
    ):
        self.strategy = strategy
        self.memory = memory
        self.min_success_rate_for_consolidate = min_success_rate_for_consolidate
        self.alignment_checks = alignment_checks or [self._default_alignment]
        self.history: List[Dict[str, Any]] = []

    def observe(self, experience: Dict[str, Any]) -> None:
        self.strategy.observe(experience)

    def step(self) -> Dict[str, Any]:
        metrics = self.strategy.improve()
        self.history.append({"ts": time.time(), "kind": "improve", "metrics": metrics})
        return metrics

    def sleep_cycle(self) -> Dict[str, Any]:
        """
        Offline consolidation loop ("sleep"):
          1) strategy improve
          2) memory.consolidate if alignment passes
        """
        metrics = self.step()
        success_rate = float(metrics.get("success_rate") or 0.0)
        gate = {
            "success_rate": success_rate,
            "metrics": metrics,
            "allow_consolidate": success_rate >= self.min_success_rate_for_consolidate,
        }
        for check in self.alignment_checks:
            if not check(gate):
                result = {
                    "status": "blocked",
                    "reason": "alignment_check_failed",
                    "metrics": metrics,
                }
                self.history.append({"ts": time.time(), "kind": "sleep", **result})
                return result

        mem_result = None
        if self.memory is not None and gate["allow_consolidate"]:
            mem_result = self.memory.consolidate()

        result = {
            "status": "ok",
            "metrics": metrics,
            "memory_consolidate": mem_result,
            "ts": time.time(),
        }
        self.history.append({"ts": time.time(), "kind": "sleep", **result})
        return result

    @staticmethod
    def _default_alignment(gate: Dict[str, Any]) -> bool:
        """
        Phase-1 safety: block consolidation only on pathological metrics.
        Extend with CTMS / policy hooks later.
        """
        # never consolidate if strategy reports explicit unsafe flag
        metrics = gate.get("metrics") or {}
        if metrics.get("unsafe") is True:
            return False
        return True
