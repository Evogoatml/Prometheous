"""
Polymorphic agent system — mosaic-backed facade.

Lives under core.mosaic (not core.orchestrator.*) because
core/orchestrator.py is a module and cannot host a subpackage.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from brain.cognitive_loader import CognitiveLoader
from core.mosaic.runtime import MosaicRuntime, get_mosaic


class PolymorphicAgentSystem:
    """
    Polymorphic Auto-Mosaic facade.

    deploy_agent(role, task) morphs a cognitive profile onto a mosaic run.
    """

    def __init__(self):
        self.cognitive = CognitiveLoader()
        try:
            self.cognitive.load("config/cognitive_config.yaml")
        except Exception:
            pass
        self.mosaic: MosaicRuntime = get_mosaic()

    def deploy_agent(self, role: str, task: str) -> Dict[str, Any]:
        """Assemble and run a mosaic with an explicit primary cognitive role."""
        constraints = ""
        try:
            constraints = self.cognitive.get_constraints_string(role)
        except Exception:
            pass
        try:
            superprompt = self.cognitive.get_superprompt(task, objective=role)
        except Exception:
            superprompt = ""

        payload = {
            "user_msg": task,
            "goal": task,
            "mosaic_role": role,
            "cognitive_constraints": constraints,
            "superprompt": superprompt,
            "polymorphic": True,
        }
        result = self.mosaic.run(task, payload)
        out = result.to_agent_result()
        out["role"] = role
        out["superprompt_chars"] = len(superprompt)
        return out

    def run(self, task: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.mosaic.run(task, payload or {}).to_agent_result()

    def list_roles(self) -> List[str]:
        try:
            return self.cognitive.get_all_roles()
        except Exception:
            return ["researcher", "coder", "reviewer"]

    def assemble_preview(self, task: str) -> List[Dict[str, Any]]:
        tiles = self.mosaic.assemble(task)
        return [
            {"name": t.name, "role": t.role, "agent": t.agent, "priority": t.priority}
            for t in tiles
        ]
