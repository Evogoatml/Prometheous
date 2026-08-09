"""Hierarchical goal decomposition and execution planning."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GoalNode:
    goal: str
    children: List["GoalNode"] = field(default_factory=list)
    node_type: str = "AND"
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None


class HierarchicalPlanner:
    """Break goals into a small execution tree and run them recursively."""

    max_depth: int = 3

    def decompose(self, goal: str, depth: int = 0) -> GoalNode:
        goal_text = (goal or "").strip()
        node = GoalNode(goal=goal_text or "unspecified goal")
        if depth >= self.max_depth or not goal_text:
            return node

        sentences = [part.strip() for part in re.split(r"[.!?]+", goal_text) if part.strip()]
        if len(sentences) > 1:
            node.node_type = "OR"
            node.children = [self.decompose(sentence, depth + 1) for sentence in sentences]
            return node

        if re.search(r"\band\b", goal_text, re.IGNORECASE):
            parts = [part.strip(" ,;") for part in re.split(r"\band\b", goal_text, flags=re.IGNORECASE) if part.strip(" ,;")]
            if len(parts) > 1:
                node.node_type = "AND"
                node.children = [self.decompose(part, depth + 1) for part in parts]
        return node

    def execute_tree(self, node: GoalNode, executor: Callable[[str], Dict[str, Any]]) -> Dict[str, Any]:
        if not node.children:
            try:
                result = executor(node.goal)
            except Exception as exc:
                logger.warning("goal execution failed for %s: %s", node.goal, exc)
                node.status = "failed"
                node.result = {"status": "failed", "error": str(exc), "goal": node.goal}
                self.backtrack(node)
                return node.result
            node.result = result if isinstance(result, dict) else {"status": "ok", "result": result}
            node.status = "done" if self._is_success(node.result) else "failed"
            if node.status == "failed":
                self.backtrack(node)
            return node.result

        if node.node_type == "OR":
            failures: List[Dict[str, Any]] = []
            for child in node.children:
                result = self.execute_tree(child, executor)
                if self._is_success(result):
                    node.status = "done"
                    node.result = {"status": "ok", "goal": node.goal, "winner": child.goal, "result": result}
                    return node.result
                failures.append(result)
                self.backtrack(child)
            node.status = "failed"
            node.result = {"status": "failed", "goal": node.goal, "failures": failures}
            self.backtrack(node)
            return node.result

        child_results: List[Dict[str, Any]] = []
        for child in node.children:
            result = self.execute_tree(child, executor)
            child_results.append(result)
            if not self._is_success(result):
                node.status = "failed"
                node.result = {"status": "failed", "goal": node.goal, "results": child_results}
                self.backtrack(node)
                return node.result
        node.status = "done"
        node.result = {"status": "ok", "goal": node.goal, "results": child_results}
        return node.result

    def backtrack(self, node: GoalNode) -> bool:
        node.status = "failed"
        if node.result is None:
            node.result = {"status": "failed", "goal": node.goal}
        logger.info("planner backtrack triggered for goal: %s", node.goal)
        return bool(node.children)

    def flatten(self, node: GoalNode) -> List[str]:
        goals = [node.goal]
        for child in node.children:
            goals.extend(self.flatten(child))
        return goals

    @staticmethod
    def _is_success(result: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(result, dict):
            return bool(result)
        if "passed" in result:
            return bool(result.get("passed"))
        if "success" in result:
            return bool(result.get("success"))
        return result.get("status", "ok") not in {"failed", "error"}
