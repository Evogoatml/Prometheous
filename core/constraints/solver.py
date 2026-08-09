"""Constraint checks for deadlines, budgets, and resources."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Constraint:
    name: str
    kind: str
    limit: float
    current: float
    unit: str = ""


class ConstraintSolver:
    """Minimal rule-based feasibility solver."""

    def __init__(self) -> None:
        self.constraints: List[Constraint] = []

    def add_constraint(self, c: Constraint) -> None:
        self.constraints.append(c)

    def check_feasibility(self, plan: Dict[str, float]) -> Tuple[bool, List[str]]:
        violations: List[str] = []
        for constraint in self.constraints:
            observed = plan.get(constraint.name, constraint.current)
            if observed > constraint.limit:
                violations.append(
                    f"{constraint.name} exceeds {constraint.limit}{constraint.unit} with {observed}{constraint.unit}"
                )
        return (not violations, violations)

    def solve(self, constraints: List[Constraint], plan: Dict[str, float]) -> Dict[str, object]:
        self.constraints = list(constraints or [])
        feasible, violations = self.check_feasibility(plan)
        solved = dict(plan or {})
        solved["feasible"] = feasible
        solved["violations"] = violations
        solved["constraint_count"] = len(self.constraints)
        return solved

    def estimate_cost(self, agent_calls: int, tokens: int) -> float:
        return round((max(tokens, 0) / 1000.0) * 0.002 + (max(agent_calls, 0) * 0.01), 6)

    def check_deadline(self, deadline_unix: float) -> bool:
        return float(deadline_unix) >= time.time()
