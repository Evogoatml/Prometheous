"""Constraint relaxation utilities for plan rescue and fallback selection."""
from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConstraintRelaxer:
    """Produce gradually relaxed constraint sets and choose feasible plans."""

    def relax(self, constraints: Dict[str, Any], attempts: int = 3) -> List[Dict[str, Any]]:
        base = dict(constraints or {})
        relaxed: List[Dict[str, Any]] = [base]
        for attempt in range(1, max(1, attempts) + 1):
            candidate = copy.deepcopy(base)
            for key, value in list(candidate.items()):
                if not isinstance(value, (int, float)):
                    continue
                lowered = key.lower()
                if "deadline" in lowered or "time" in lowered or "latency" in lowered:
                    candidate[key] = round(value * (1.0 + (0.2 * attempt)), 4)
                elif "budget" in lowered or "cost" in lowered:
                    candidate[key] = round(value * (1.0 + (0.1 * attempt)), 4)
                elif "quality" in lowered or "score" in lowered:
                    candidate[key] = round(value * max(0.5, 1.0 - (0.1 * attempt)), 4)
                elif "resource" in lowered or "capacity" in lowered:
                    candidate[key] = round(value * (1.0 + (0.15 * attempt)), 4)
            candidate["relaxation_attempt"] = attempt
            relaxed.append(candidate)
        return relaxed

    def find_best_feasible(self, plans: List[Dict[str, Any]], scorer: Callable[[Dict[str, Any]], float]) -> Optional[Dict[str, Any]]:
        feasible = [plan for plan in plans if isinstance(plan, dict) and plan.get("feasible", True)]
        if not feasible:
            return None
        best_plan: Optional[Dict[str, Any]] = None
        best_score: Optional[float] = None
        for plan in feasible:
            try:
                score = float(scorer(plan))
            except Exception as exc:
                logger.warning("plan scoring failed: %s", exc)
                continue
            if best_score is None or score > best_score:
                best_plan = plan
                best_score = score
        return best_plan
