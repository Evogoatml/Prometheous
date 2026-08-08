"""
Skill library — persistent lookup/record for agent solutions.
Stores known task→solution mappings in memory.
"""
import json
import os
import time
from typing import Any, Dict, Optional


class SkillLibrary:
    """Persistent skill/solution cache. Lookup by task pattern."""

    def __init__(self, storage_path: str = ""):
        self._skills: Dict[str, dict] = {}
        self._storage_path = storage_path

    def lookup(self, task: str) -> Optional[Any]:
        """Find a stored solution by task prefix match."""
        task_lower = task.lower()
        for pattern, entry in self._skills.items():
            if pattern in task_lower or task_lower in pattern:
                return type("Skill", (), {"solution": entry["solution"]})()
        return None

    def record(self, task: str, solution: str, success: bool = True):
        """Store a new skill solution."""
        key = task.lower().strip()[:80]
        self._skills[key] = {
            "solution": solution,
            "success": success,
            "timestamp": time.time(),
        }

    def save(self, path: str = ""):
        path = path or self._storage_path
        if path:
            with open(path, "w") as f:
                json.dump(self._skills, f, indent=2)

    def load(self, path: str = ""):
        path = path or self._storage_path
        if path and os.path.exists(path):
            with open(path) as f:
                self._skills = json.load(f)


tool_agent = SkillLibrary()