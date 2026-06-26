"""
Prometheous orchestrator — the brain's task dispatcher.

Responsibilities:
  - Take a Decision from the decision engine
  - Resolve it to a real agent in swarm/ (or fail with reason)
  - Track lifecycle (queued → running → done / failed)
  - Update utils.state so restarts resume correctly
  - NOT call the LLM. The LLM is called only by the gateway.
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.state import state
from utils.helpers import generate_id

logger = logging.getLogger(__name__)


@dataclass
class Task:
    task_id: str
    intent: str
    agent: Optional[str]
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = "queued"   # queued | running | done | failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


class Orchestrator:
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self._agent_registry: Dict[str, Any] = {}  # agent_name -> instance

    # agent registry -------------------------------------------------------
    def register_agent(self, name: str, agent: Any) -> None:
        self._agent_registry[name] = agent
        logger.info("agent registered: %s", name)

    def list_agents(self) -> List[str]:
        return list(self._agent_registry.keys())

    def get_agent(self, name: str) -> Optional[Any]:
        return self._agent_registry.get(name)

    # dispatch -------------------------------------------------------------
    def dispatch(self, decision, payload: Optional[Dict[str, Any]] = None) -> Task:
        """
        `decision` is a core.decision.Decision. We translate it into a Task
        and either run it (if it has a registered agent), run a skill, or
        mark it as awaiting an LLM response.
        """
        task = Task(
            task_id=generate_id("t-"),
            intent=decision.action,
            agent=decision.agent,
            payload=payload or {},
        )

        # Branch 1: create_skill → spawn or fetch a skill builder
        if decision.action == "create_skill":
            task.agent = "skill_builder"
            self._run_agent(task, {"skill_name": decision.skill_name})
            return task

        # Branch 2: run_skill → invoke skill by name
        if decision.action == "run_skill":
            self._run_skill(task, decision.skill_name)
            return task

        # Branch 3: dispatch to a registered agent
        if decision.action == "dispatch" and decision.agent:
            self._run_agent(task, task.payload)
            return task

        # Branch 4: respond-only (LLM gateway will handle phrasing)
        if decision.action == "respond":
            task.status = "done"
            task.result = {"intent": "respond", "reason": decision.reason}
            return task

        # unknown
        task.status = "failed"
        task.error = f"unhandled action: {decision.action}"
        return task

    # internals ------------------------------------------------------------
    def _run_agent(self, task: Task, payload: Dict[str, Any]) -> None:
        task.status = "running"
        task.started_at = time.time()
        state.active_tasks.append({"id": task.task_id, "agent": task.agent, "ts": task.started_at})
        if task.agent and task.agent not in state.active_agents:
            state.active_agents.append(task.agent)

        agent = self.get_agent(task.agent) if task.agent else None
        if agent is None:
            task.status = "failed"
            task.error = f"no agent registered: {task.agent}"
            task.finished_at = time.time()
            state.total_tasks_completed += 1
            return

        try:
            if hasattr(agent, "execute"):
                result = agent.execute(payload)
            elif hasattr(agent, "run"):
                result = agent.run(payload)
            else:
                result = {"status": "noop", "reason": "agent has no execute/run"}
            task.result = result if isinstance(result, dict) else {"result": str(result)}
            task.status = "done" if task.result.get("status") != "failed" else "failed"
        except Exception as e:
            logger.exception("agent %s failed: %s", task.agent, e)
            task.status = "failed"
            task.error = str(e)
        finally:
            task.finished_at = time.time()
            state.total_tasks_completed += 1
            # purge from active lists
            state.active_tasks = [t for t in state.active_tasks if t.get("id") != task.task_id]

    def _run_skill(self, task: Task, skill_name: Optional[str]) -> None:
        task.status = "running"
        task.started_at = time.time()
        agent = self.get_agent("skill_runner")
        if not agent:
            task.status = "failed"
            task.error = "no skill_runner agent registered"
        else:
            try:
                result = agent.execute({"skill_name": skill_name, **task.payload})
                task.result = result if isinstance(result, dict) else {"result": str(result)}
                task.status = "done"
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
        task.finished_at = time.time()
        state.total_tasks_completed += 1


# Single shared instance
orchestrator = Orchestrator()
