"""Verification helpers for files, code, URLs, and structured results."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List
from urllib.parse import urlparse

try:
    import requests
except Exception:
    requests = None

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    passed: bool
    checks: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    score: float = 0.0


class VerificationLayer:
    """Lightweight verification routines with graceful degradation."""

    def __init__(self) -> None:
        # Bounded record of the most recent verification per task, so
        # collect_feedback can report something real instead of a fixed
        # "pending" placeholder.
        self._by_task: "Dict[str, VerificationResult]" = {}
        self._task_order: List[str] = []
        self._max_tasks = 500

    def record_result(self, task_id: str, result: VerificationResult) -> None:
        if not task_id:
            return
        if task_id not in self._by_task:
            self._task_order.append(task_id)
        self._by_task[task_id] = result
        while len(self._task_order) > self._max_tasks:
            stale = self._task_order.pop(0)
            self._by_task.pop(stale, None)

    def verify_file(self, path: str) -> VerificationResult:
        checks: List[str] = []
        failures: List[str] = []
        if os.path.exists(path):
            checks.append("exists")
        else:
            failures.append("file does not exist")
        if os.path.isfile(path):
            checks.append("is_file")
        elif os.path.exists(path):
            failures.append("path is not a file")
        if os.path.exists(path):
            try:
                if os.path.getsize(path) > 0:
                    checks.append("non_empty")
                else:
                    failures.append("file is empty")
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    handle.read(1)
                checks.append("readable")
            except Exception as exc:
                failures.append(f"read failed: {exc}")
        return self._result(checks, failures)

    def verify_code(self, code: str, language: str = "python") -> VerificationResult:
        checks: List[str] = []
        failures: List[str] = []
        text = code or ""
        if text.strip():
            checks.append("non_empty")
        else:
            failures.append("code is empty")
        if language.lower() == "python" and text.strip():
            try:
                compile(text, "<verification>", "exec")
                checks.append("python_compile_ok")
            except SyntaxError as exc:
                failures.append(f"syntax error: {exc}")
        elif text.count("(") != text.count(")"):
            failures.append("unbalanced parentheses detected")
        if "TODO" in text:
            failures.append("contains TODO marker")
        if "eval(" in text:
            failures.append("contains eval()")
        return self._result(checks, failures)

    def verify_url(self, url: str) -> VerificationResult:
        checks: List[str] = []
        failures: List[str] = []
        parsed = urlparse(url or "")
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            checks.append("valid_format")
        else:
            failures.append("invalid URL format")
        if requests is not None and not failures:
            try:
                response = requests.head(url, timeout=5, allow_redirects=True)
                if response.status_code < 400:
                    checks.append(f"head_ok:{response.status_code}")
                else:
                    failures.append(f"HEAD status {response.status_code}")
            except Exception as exc:
                failures.append(f"HEAD request failed: {exc}")
        elif requests is None:
            checks.append("requests_unavailable_skipped")
        return self._result(checks, failures)

    def verify_result(self, result: Dict[str, Any], schema: Dict[str, Any]) -> VerificationResult:
        checks: List[str] = []
        failures: List[str] = []
        payload = result or {}
        required = list((schema or {}).get("required", []))
        for key in required:
            if payload.get(key) is not None:
                checks.append(f"required:{key}")
            else:
                failures.append(f"missing required key: {key}")
        return self._result(checks, failures)

    def collect_feedback(self, task_id: str, query: str) -> Dict[str, Any]:
        result = self._by_task.get(task_id)
        if result is None:
            return {"task_id": task_id, "query": query, "feedback": "no verification recorded"}
        feedback = "passed" if result.passed else "failed"
        return {
            "task_id": task_id,
            "query": query,
            "feedback": feedback,
            "score": result.score,
            "checks": list(result.checks),
            "failures": list(result.failures),
        }

    @staticmethod
    def _result(checks: List[str], failures: List[str]) -> VerificationResult:
        total = len(checks) + len(failures)
        score = 1.0 if total == 0 else round(len(checks) / total, 4)
        return VerificationResult(passed=not failures, checks=checks, failures=failures, score=score)
