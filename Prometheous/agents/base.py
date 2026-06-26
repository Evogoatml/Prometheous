from typing import Dict, Any, Optional


class BaseAgent:
    """Base class for all agents. Tracks state and identity."""

    def __init__(self):
        self._status = "idle"
        self._current_task = ""

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def description(self) -> str:
        return ""

    def update_state(self, status: str = None, current_task: str = None):
        if status:
            self._status = status
        if current_task:
            self._current_task = current_task

    def execute(self, task: str, context: Optional[Dict[str, Any]] = None) -> str:
        raise NotImplementedError