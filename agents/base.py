from typing import Dict, Any, Optional
import time

from brain.cognitive_loader import CognitiveLoader


class BaseAgent:
    """
    Base class for agents/ specialist modules (the ones placed under agents/).
    Provides:
      - identity (name/role/specialty)
      - state tracking
      - cognitive loader integration (hot-reloadable constraints + superprompt)
      - standard execute(payload) contract used by orchestrator
    """

    name: str = "base"
    role: str = "general"
    specialty: str = "general purpose"

    def __init__(self):
        self._status = "idle"
        self._current_task: str = ""
        self.tasks_completed: int = 0
        self.created_at: float = time.time()
        self.active: bool = False

        # Cognitive integration (from moved brain/cognitive_loader)
        try:
            self.cognitive_loader = CognitiveLoader()
            # try to load if config present; ignore if not
            try:
                self.cognitive_loader.load("config/cognitive_config.yaml")
            except Exception:
                pass
        except Exception:
            self.cognitive_loader = None

        self.role = getattr(self, "role", "researcher")

    @property
    def description(self) -> str:
        return f"{self.role} - {self.specialty}"

    def update_state(self, status: Optional[str] = None, current_task: Optional[str] = None):
        if status:
            self._status = status
        if current_task:
            self._current_task = current_task

    def get_cognitive_constraints(self) -> str:
        if not self.cognitive_loader:
            return ""
        return self.cognitive_loader.get_constraints_string(self.role)

    def get_superprompt(self, task: str = "") -> str:
        if not self.cognitive_loader:
            return task
        return self.cognitive_loader.get_superprompt(task or self._current_task or "general task")

    def on_deploy(self) -> None:
        self.active = True

    def on_recall(self) -> None:
        self.active = False

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Subclasses override this.
        Default returns a structured response so the system stays functional.
        """
        self.tasks_completed += 1
        self.update_state(status="running", current_task=str(payload)[:100])
        result = {
            "status": "ok",
            "agent": getattr(self, "name", self.__class__.__name__),
            "role": self.role,
            "specialty": self.specialty,
            "received": payload,
            "note": "base execute - override in subclass",
        }
        self.update_state(status="idle")
        return result

    def status(self) -> Dict[str, Any]:
        return {
            "name": getattr(self, "name", self.__class__.__name__),
            "role": self.role,
            "specialty": self.specialty,
            "active": self.active,
            "tasks": self.tasks_completed,
            "uptime_s": time.time() - self.created_at,
        }
