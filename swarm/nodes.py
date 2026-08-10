
"""
Swarm nodes — concrete agent implementations that ship with the framework.

These are the default specialists. The system registers them all on
boot. Real specialists (loaded from agents/) are also registered and
take precedence by name.
"""
import logging
import time
from typing import Any, Dict

from swarm.base import BaseAgent
from utils.config import cfg

logger = logging.getLogger(__name__)


class ScannerNode(BaseAgent):
    name = "scanner"
    role = "Scanner"
    specialty = "port scanning, service detection, vulnerability identification"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        target = payload.get("target") or payload.get("host") or "localhost"
        ports = payload.get("ports") or list(cfg.SCAN_PORTS)
        self.tasks_completed += 1
        logger.info("scanner running against %s", target)
        try:
            from controllers.portscan import sync_scan
            results = sync_scan(target, ports)
        except Exception as exc:
            logger.exception("scanner failed against %s", target)
            return {"status": "failed", "agent": self.name, "target": target, "error": str(exc)}
        open_ports = [r["port"] for r in results if r.get("status") == "open"]
        return {
            "status": "ok",
            "agent": self.name,
            "target": target,
            "result": {
                "scanned": True,
                "open_ports": open_ports,
                "open_count": len(open_ports),
                "services": results,
            },
        }


class SkillBuilderNode(BaseAgent):
    name = "skill_builder"
    role = "SkillBuilder"
    specialty = "creating new skills from user intent"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        skill_name = payload.get("skill_name", "unnamed_skill")
        self.tasks_completed += 1
        return {
            "status": "ok",
            "agent": self.name,
            "result": {
                "action": "would_create_skill",
                "skill_name": skill_name,
                "next_steps": [
                    "define inputs/outputs",
                    "write handler in agents/<name>.py",
                    "register with orchestrator",
                ],
            },
        }


class SkillRunnerNode(BaseAgent):
    name = "skill_runner"
    role = "SkillRunner"
    specialty = "invoking a named skill"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        skill_name = payload.get("skill_name")
        self.tasks_completed += 1
        if not skill_name:
            return {"status": "failed", "agent": self.name, "error": "no skill_name supplied"}

        agent = None
        try:
            from core.orchestrator import orchestrator
            agent = orchestrator.get_agent(skill_name)
        except Exception:
            agent = None
        if agent is None:
            try:
                from swarm.orchestrator import orb
                agent = orb.get(skill_name)
            except Exception:
                agent = None
        if agent is None:
            return {
                "status": "failed",
                "agent": self.name,
                "error": f"no agent registered for skill '{skill_name}'",
            }

        try:
            if hasattr(agent, "execute"):
                result = agent.execute(payload)
            elif hasattr(agent, "run"):
                result = agent.run(payload)
            else:
                result = {"status": "noop", "reason": "agent has no execute/run"}
        except Exception as exc:
            logger.exception("skill '%s' raised", skill_name)
            result = {"status": "failed", "agent": self.name, "error": str(exc)}

        result["skill"] = skill_name
        return result


# Single list used by main.py to register default agents.
DEFAULT_NODES = [
    ScannerNode,
    SkillBuilderNode,
    SkillRunnerNode,
]
