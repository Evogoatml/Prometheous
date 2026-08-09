"""Adversarial and edge-case testing helpers."""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)


class AdversarialTester:
    """Run lightweight hallucination and robustness checks."""

    def detect_hallucination(self, response: str, context: str) -> Dict[str, Any]:
        text = response or ""
        ctx = context or ""
        issues: List[str] = []
        if re.search(r"\b\d{4,}\b", text) and not re.search(r"\b\d{4,}\b", ctx):
            issues.append("numeric claim without supporting context")
        if "as mentioned above" in text.lower() and "mentioned above" not in ctx.lower():
            issues.append("undefined backward reference")
        if "always" in text.lower() and "never" in text.lower():
            issues.append("self-contradictory absolutes")
        return {"hallucination_risk": bool(issues), "issues": issues, "score": max(0.0, 1.0 - (0.3 * len(issues)))}

    def test_edge_cases(self, agent_callable: Callable[[Dict[str, Any]], Any], base_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        long_string = "x" * 10000
        cases = [
            ("empty", {}),
            ("none_values", {"input": None, **dict(base_payload or {})}),
            ("long_string", {"input": long_string, **dict(base_payload or {})}),
            ("special_chars", {"input": "!@#$%^&*()[]{}\\n\\t", **dict(base_payload or {})}),
        ]
        results: List[Dict[str, Any]] = []
        for name, payload in cases:
            try:
                output = agent_callable(payload)
                results.append({"case": name, "success": True, "output": output})
            except Exception as exc:
                results.append({"case": name, "success": False, "error": str(exc)})
        return results

    def detect_contradiction(self, outputs: List[str]) -> List[Tuple[int, int, str]]:
        contradictions: List[Tuple[int, int, str]] = []
        for i, first in enumerate(outputs or []):
            first_norm = (first or "").lower()
            for j in range(i + 1, len(outputs or [])):
                second_norm = (outputs[j] or "").lower()
                if not first_norm or not second_norm:
                    continue
                if first_norm == second_norm:
                    continue
                if (" is " in first_norm and " is not " in second_norm) or (" is not " in first_norm and " is " in second_norm):
                    contradictions.append((i, j, "affirmation vs negation"))
                elif ("always" in first_norm and "never" in second_norm) or ("never" in first_norm and "always" in second_norm):
                    contradictions.append((i, j, "absolute contradiction"))
        return contradictions
