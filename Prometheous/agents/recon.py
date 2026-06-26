from swarm.base import BaseAgent
from typing import Any, Dict


class ReconAgent(BaseAgent):
    name = "recon"
    role = "Recon"
    specialty = "placeholder"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        return {"status": "ok", "agent": self.name, "result": {}}