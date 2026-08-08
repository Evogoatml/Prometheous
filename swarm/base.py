
"""
Base agent for the Prometheous swarm.

Every concrete agent (in agents/ or elsewhere) is registered with the
orchestrator by name. The orchestrator's dispatch() looks up the agent
and calls its execute(payload) method.

This base class provides:
  - name / role / specialty fields for display
  - lifecycle hooks (on_deploy, on_recall)
  - cognitive integration via brain/cognitive_loader (hot-reloadable)
  - a default execute() that returns a structured "not_implemented"
    stub so the swarm keeps working even when specialists are missing.
"""
import logging
import time
from typing import Any, Dict, Optional

from brain.cognitive_loader import CognitiveLoader

logger = logging.getLogger(__name__)


class BaseAgent:
    name: str = "base"
    role: str = "base"
    specialty: str = "general"
    version: str = "0.1.0"

    def __init__(self):
        self.active: bool = False
        self.last_active: float = 0.0
        self.tasks_completed: int = 0
        self.created_at: float = time.time()
        self.cognitive_loader = None

    def _init_cognitive_loader(self) -> None:
        if self.cognitive_loader is not None:
            return
        try:
            from brain.cognitive_loader import CognitiveLoader
            loader = CognitiveLoader()
            try:
                loader.load("config/cognitive_config.yaml")
            except Exception:
                pass
            self.cognitive_loader = loader
        except Exception:
            self.cognitive_loader = None

    # lifecycle -----------------------------------------------------------
    def on_deploy(self) -> None:
        self.active = True
        self.last_active = time.time()
        logger.info("agent deployed: %s (%s)", self.name, self.role)

    def on_recall(self) -> None:
        self.active = False
        logger.info("agent recalled: %s", self.name)

    # cognitive helpers (from structured cognitive loader) -----------------
    def get_cognitive_constraints(self) -> str:
        if self.cognitive_loader:
            try:
                return self.cognitive_loader.get_constraints_string(self.role)
            except Exception:
                return ""
        return ""

    def build_cognitive_prompt(self, task: str = "") -> str:
        """Build a prompt that includes the dynamic superprompt + role constraints."""
        base = ""
        if self.cognitive_loader:
            try:
                base = self.cognitive_loader.get_superprompt(task or "current task")
            except Exception:
                pass
        constraints = self.get_cognitive_constraints()
        if constraints:
            base = f"{base}\n\nCOGNITIVE CONSTRAINTS ({self.role}):\n{constraints}"
        return base.strip()

    # main entry point ----------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Concrete agents override this. Default returns a stub so the
        swarm stays functional when an agent is registered but empty.

        If orchestrator has .cogno_port (from real cogno attach), use it
        for deeper internal thought before returning.
        """
        self.tasks_completed += 1

        # Use attached cogno substrate if present (real integration path)
        cogno_port = getattr(getattr(self, 'orchestrator', None), 'cogno_port', None) or \
                     getattr(globals().get('orchestrator', None), 'cogno_port', None)
        if cogno_port and hasattr(cogno_port, 'think'):
            try:
                thought = cogno_port.think(str(payload)[:200])
                return {
                    "status": "ok",
                    "agent": self.name,
                    "cogno_thought": str(thought)[:300],
                    "result": "cogno-enhanced execution",
                }
            except Exception:
                pass

        return {
            "status": "not_implemented",
            "agent": self.name,
            "role": self.role,
            "message": f"agent '{self.name}' received: {str(payload)[:200]}",
        }

    # helpers -------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "specialty": self.specialty,
            "active": self.active,
            "tasks": self.tasks_completed,
            "version": self.version,
            "uptime_s": time.time() - self.created_at,
        }
