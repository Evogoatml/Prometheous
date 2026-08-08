"""
Error-aware module learning — tracks successes, failures, and synaptic links.
Adapted from adaptive_vault neural_core.py.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from utils.config import cfg

BRAIN_PATH = cfg.DATA_DIR / "learning" / "brain_core.json"
MAX_ERRORS = 200


class AwarenessCore:
    """Evolving awareness model: module health, error memory, concept drift."""

    def __init__(self):
        BRAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.brain = self._load()
        self._session: list[tuple[str, str]] = []

    def _load(self) -> dict:
        if BRAIN_PATH.exists():
            with open(BRAIN_PATH, encoding="utf-8") as f:
                return json.load(f)
        return {
            "modules": {},
            "concepts": {"stability": 0.5, "efficiency": 0.5, "awareness": 0.5},
            "links": {},
            "errors": [],
            "evolution": 0,
        }

    def _save(self) -> None:
        with open(BRAIN_PATH, "w", encoding="utf-8") as f:
            json.dump(self.brain, f, indent=2)

    def record_experience(
        self,
        module: str,
        result: str = "success",
        *,
        latency: float | None = None,
        error: str | None = None,
        context: dict | None = None,
    ) -> None:
        m = self.brain["modules"].get(
            module, {"success": 0, "failure": 0, "avg_latency": None, "last_error": None}
        )
        if result == "success":
            m["success"] += 1
        else:
            m["failure"] += 1
            if error:
                m["last_error"] = error
                self._record_error(module, error, context)
        if latency is not None:
            prev = m.get("avg_latency")
            m["avg_latency"] = latency if prev is None else (prev * 0.7 + latency * 0.3)
        self.brain["modules"][module] = m
        self._session.append((module, result))
        self._form_links(module, result)
        self._evolve_concepts()
        self._save()

    def _record_error(self, module: str, error: str, context: dict | None) -> None:
        entry = {
            "ts": time.time(),
            "module": module,
            "error": error[:500],
            "context": context or {},
        }
        errors = self.brain.setdefault("errors", [])
        errors.append(entry)
        self.brain["errors"] = errors[-MAX_ERRORS:]

    def _form_links(self, module: str, result: str) -> None:
        if len(self._session) < 2:
            return
        prev = self._session[-2][0]
        links = self.brain["links"].setdefault(prev, {})
        links.setdefault(module, 0.0)
        delta = 0.1 if result == "success" else -0.05
        links[module] = round(max(0.0, min(1.0, links[module] + delta)), 3)

    def _evolve_concepts(self) -> None:
        modules = self.brain["modules"]
        total = sum(m["success"] + m["failure"] for m in modules.values()) or 1
        successes = sum(m["success"] for m in modules.values())
        stability = successes / total
        failures = total - successes
        efficiency = max(0.0, 1.0 - (failures / total))
        awareness = min(1.0, math.log1p(total) / 10)
        self.brain["concepts"].update({
            "stability": round(stability, 3),
            "efficiency": round(efficiency, 3),
            "awareness": round(awareness, 3),
        })
        self.brain["evolution"] += 1

    def get_concepts(self) -> dict:
        return dict(self.brain.get("concepts", {}))

    def get_module_stats(self) -> dict:
        out = {}
        for name, m in self.brain.get("modules", {}).items():
            total = m["success"] + m["failure"]
            out[name] = {
                "success": m["success"],
                "failure": m["failure"],
                "success_rate": round(m["success"] / total, 2) if total else 0.0,
                "avg_latency": m.get("avg_latency"),
                "last_error": m.get("last_error"),
            }
        return out

    def recent_errors(self, limit: int = 10) -> list[dict]:
        return list(self.brain.get("errors", [])[-limit:])

    def error_patterns(self) -> list[dict]:
        """Aggregate errors by module for awareness of recurring failure points."""
        counts: dict[str, dict[str, Any]] = {}
        for e in self.brain.get("errors", []):
            mod = e["module"]
            if mod not in counts:
                counts[mod] = {"module": mod, "count": 0, "last_error": e["error"], "samples": []}
            counts[mod]["count"] += 1
            if len(counts[mod]["samples"]) < 3:
                counts[mod]["samples"].append(e["error"])
        return sorted(counts.values(), key=lambda x: x["count"], reverse=True)