
"""
Base agent for the Prometheous swarm.

Every concrete agent (in agents/ or elsewhere) is registered with the
orchestrator by name. The orchestrator's dispatch() looks up the agent
and calls its execute(payload) method.

This base class provides:
  - name / role / specialty fields for display
  - lifecycle hooks (on_deploy, on_recall)
  - a default execute() that returns a structured "not_implemented"
    stub so the swarm keeps working even when specialists are missing.
"""
import logging
import time
from typing import Any, Dict, Optional

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

    # lifecycle -----------------------------------------------------------
    def on_deploy(self) -> None:
        self.active = True
        self.last_active = time.time()
        logger.info("agent deployed: %s (%s)", self.name, self.role)

    def on_recall(self) -> None:
        self.active = False
        logger.info("agent recalled: %s", self.name)

    # main entry point ----------------------------------------------------
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Concrete agents override this. Default returns a stub so the
        swarm stays functional when an agent is registered but empty.
        """
        self.tasks_completed += 1
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
