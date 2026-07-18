from swarm.base import BaseAgent
from learning.healing import self_healing
from typing import Any, Dict

# Use structured controllers for real work
try:
    from controllers.tool_controller import tools
except Exception:
    tools = None


class ScannerAgent(BaseAgent):
    name = "scanner"
    role = "Scanner"
    specialty = "port scanning, service detection"

    @self_healing
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        target = payload.get("target") or payload.get("user_msg", "localhost")
        if tools:
            scan = tools.run("port_scan", host=target, ports=[22, 80, 443, 8080])
            return {"status": "ok", "agent": self.name, "target": target, "result": scan}
        return {
            "status": "ok",
            "agent": self.name,
            "target": target,
            "result": {"note": "tools controller not available, stub scan"},
        }