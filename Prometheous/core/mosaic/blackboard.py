"""Shared workspace for a mosaic run — tiles read/write observations here."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Blackboard:
    goal: str
    created_at: float = field(default_factory=time.time)
    notes: List[str] = field(default_factory=list)
    observations: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def write(self, tile: str, payload: Any) -> None:
        self.observations[tile] = payload
        self.notes.append(f"{tile}:ok")

    def fail(self, tile: str, error: str) -> None:
        self.errors.append(f"{tile}: {error}")
        self.notes.append(f"{tile}:fail")

    def add_artifact(self, path: str) -> None:
        if path and path not in self.artifacts:
            self.artifacts.append(path)

    def research_text(self) -> str:
        for key in ("research", "web_search", "knowledge"):
            obs = self.observations.get(key)
            if isinstance(obs, dict):
                t = obs.get("formatted") or obs.get("message") or ""
                if t:
                    return str(t)[:3000]
        return ""

    def snapshot(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "notes": list(self.notes),
            "artifacts": list(self.artifacts),
            "errors": list(self.errors),
            "tiles": list(self.observations.keys()),
            "meta": dict(self.meta),
        }
