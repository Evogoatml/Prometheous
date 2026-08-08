
"""
Swarm orchestrator.

Responsible for:
  - Agent registry: register, lookup, list agents by name
  - Dispatch: pass a Decision from core.orchestrator to the right agent
  - Lifecycle: deploy / recall agents on demand
  - Simple priority routing (user-facing I/O gets handled first)

No LLM calls here. Pure system-side routing.
"""
import logging
import time
from typing import Any, Dict, List, Optional, Type

from swarm.base import BaseAgent

logger = logging.getLogger(__name__)


class SwarmOrchestrator:
    """
    Singleton-style orchestrator. The core decision engine hands it
    a Decision dict, and it resolves that to an agent + payload.
    """

    def __init__(self):
        self._registry: Dict[str, BaseAgent] = {}
        self._history: List[Dict[str, Any]] = []
        self.started_at: float = time.time()

    # registry ------------------------------------------------------------
    def register(self, agent: BaseAgent) -> None:
        if agent.name in self._registry:
            logger.info("overwriting agent: %s", agent.name)
        self._registry[agent.name] = agent
        logger.info("agent registered: %s (%s)", agent.name, agent.role)

    def register_class(self, cls: Type[BaseAgent]) -> None:
        self.register(cls())

    def get(self, name: str) -> Optional[BaseAgent]:
        return self._registry.get(name)

    def list_agents(self) -> List[Dict[str, Any]]:
        return [a.status() for a in self._registry.values()]

    # dispatch ------------------------------------------------------------
    def dispatch(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        Accept a Decision dict from the core decision engine and route it.

        Decision shape (from core.decision.py):
          {"action": str, "agent": str, "payload": dict, "priority": int|str}

        Returns the agent's execute() result dict, augmented with
        dispatcher metadata.
        """
        agent_name = (decision.get("agent") or "report").lower()
        payload = decision.get("payload") or {}
        priority = decision.get("priority", 0)

        agent = self._registry.get(agent_name)
        if agent is None:
            logger.warning("unknown agent '%s' — falling back to report", agent_name)
            agent = self._registry.get("report")

        if agent is None:
            return {
                "status": "failed",
                "error": f"agent '{agent_name}' not found and no fallback",
                "decision": decision,
            }

        tick_start = time.time()
        try:
            result = agent.execute(payload)
        except Exception as e:
            logger.exception("agent '%s' raised", agent_name)
            result = {"status": "error", "agent": agent_name, "error": str(e)}

        tick_ms = int((time.time() - tick_start) * 1000)

        record = {
            "agent": agent_name,
            "action": decision.get("action"),
            "status": result.get("status", "unknown"),
            "priority": priority,
            "tick_ms": tick_ms,
            "ts": time.time(),
        }
        self._history.append(record)

        # Attach dispatcher metadata to the result
        result["_dispatch"] = record
        return result

    # lifecycle -----------------------------------------------------------
    def deploy_all(self) -> None:
        for a in self._registry.values():
            a.on_deploy()

    def recall_all(self) -> None:
        for a in self._registry.values():
            a.on_recall()

    # observability -------------------------------------------------------
    def recent_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._history[-limit:]

    def summary(self) -> Dict[str, Any]:
        return {
            "agents": len(self._registry),
            "dispatches": len(self._history),
            "uptime_s": int(time.time() - self.started_at),
        }


# Module-level singleton. Other modules do:
#   from swarm.orchestrator import orb
orb = SwarmOrchestrator()
