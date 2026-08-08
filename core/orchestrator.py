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
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.state import state
from utils.helpers import generate_id, payload_hash

# Result memoization — bounded LRU keyed on (agent_name, payload_hash).
# Skip agents that have external side effects or mutate state.
_CACHE_MAX = int(os.environ.get("PROM_DISPATCH_CACHE_MAX", "256"))
_CACHE_TTL_S = float(os.environ.get("PROM_DISPATCH_CACHE_TTL", "300"))
_SKIP_CACHE_AGENTS = frozenset({
    "telegram", "skill_runner", "skill_builder", "task", "task_agent",
    "mcp_tools", "ghost_sentinel", "growth", "mission", "mosaic",
    "neuro_swarm", "scanner", "swarm_orchestrator",
})

# Bus from structured layout (pub/sub for agent coordination)
try:
    from bus.agent_bus import bus
except Exception:
    bus = None

# Paradox integration (brain/paradox structured components now affect flow)
try:
    from paradox.paradox_aware_orchestrator import paradox as paradox_auditor
except Exception:
    paradox_auditor = None

logger = logging.getLogger(__name__)

try:
    from learning import learner
except Exception:
    learner = None

try:
    from learning.trajectory import record_task as record_trajectory
except Exception:
    record_trajectory = None

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
        # Bounded LRU: (agent_name, payload_hash) -> (result_dict, ts)
        # Pure-CPU/lookup agents only. Side-effect agents bypass via _SKIP_CACHE_AGENTS.
        self._result_cache: "OrderedDict[tuple, tuple]" = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0

    def _cache_get(self, agent: Optional[str], payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Side-effect agents and disabled cache never enter the lookup
        if not agent or agent in _SKIP_CACHE_AGENTS or _CACHE_MAX <= 0:
            return None
        key = (agent, payload_hash(payload))
        entry = self._result_cache.get(key)
        if entry is None:
            return None
        result, ts = entry
        if (time.time() - ts) > _CACHE_TTL_S:
            try:
                del self._result_cache[key]
            except KeyError:
                pass
            return None
        # NOTE: deliberately skip move_to_end() on hits — the LRU recency
        # bookkeeping is dominated by inserts; on hits it's a no-op win
        # that adds an O(1) double-link touch. Only insert/put reorders.
        return result

    def _cache_put(self, agent: Optional[str], payload: Dict[str, Any], result: Dict[str, Any]) -> None:
        if not agent or agent in _SKIP_CACHE_AGENTS or _CACHE_MAX <= 0:
            return
        if not isinstance(result, dict) or result.get("status") == "failed":
            return  # don't cache failures
        key = (agent, payload_hash(payload))
        self._result_cache[key] = (result, time.time())
        # Only reorder on insert; eviction correctness depends on it
        self._result_cache.move_to_end(key)
        while len(self._result_cache) > _CACHE_MAX:
            self._result_cache.popitem(last=False)

    def clear_cache(self) -> None:
        self._result_cache.clear()

    def cache_stats(self) -> Dict[str, int]:
        return {
            "size": len(self._result_cache),
            "max": _CACHE_MAX,
            "hits": self._cache_hits,
            "misses": self._cache_misses,
        }

    # agent registry -------------------------------------------------------
    def register_agent(self, name: str, agent: Any) -> None:
        self._agent_registry[name] = agent
        logger.info("agent registered: %s", name)

    def list_agents(self) -> List[str]:
        return list(self._agent_registry.keys())

    def get_agent(self, name: str) -> Optional[Any]:
        agent = self._agent_registry.get(name)
        if agent is None:
            try:
                from swarm.orchestrator import orb
                agent = orb.get(name)
            except Exception:
                pass
        return agent

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
        if bus:
            try:
                bus.publish_sync("task.queued", {"task_id": task.task_id, "intent": task.intent, "agent": task.agent}, source="orchestrator")
            except Exception:
                pass

        # Branch 1: create_skill → spawn or fetch a skill builder
        if decision.action == "create_skill":
            task.agent = "skill_builder"
            self._run_agent(task, {"skill_name": decision.skill_name})
            return task

        # Branch 2: run_skill → invoke skill by name
        if decision.action == "run_skill":
            self._run_skill(task, decision.skill_name)
            return task

        # Branch 3: MCP function call → mcp_tools agent
        if decision.action == "call_tool" and decision.tool_name:
            task.agent = "mcp_tools"
            tool_payload = {
                **task.payload,
                "tool_name": decision.tool_name,
                "tool_args": decision.tool_args or {},
                "confidence": decision.confidence,
                "source": "orchestrator",
            }
            self._run_agent(task, tool_payload)
            return task

        # Branch 4: dispatch to a registered agent
        if decision.action == "dispatch" and decision.agent:
            self._run_agent(task, task.payload)
            return task

        # Branch 5: respond-only (LLM gateway will handle phrasing)
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
        if bus:
            try:
                bus.publish_sync("task.running", {"task_id": task.task_id, "agent": task.agent}, source="orchestrator")
            except Exception:
                pass

        agent = self.get_agent(task.agent) if task.agent else None
        if agent is None:
            task.status = "failed"
            task.error = f"no agent registered: {task.agent}"
            task.finished_at = time.time()
            if record_trajectory:
                try:
                    record_trajectory(
                        task_id=task.task_id,
                        intent=task.intent,
                        agent=task.agent,
                        status=task.status,
                        payload=payload,
                        error=task.error,
                        started_at=task.started_at,
                        finished_at=task.finished_at,
                    )
                except Exception:
                    logger.debug("trajectory record failed", exc_info=True)
            state.total_tasks_completed += 1
            return

        # Cache hit fast path — minimum work, maximum throughput.
        # No trajectory write, no learner outcome, no bus publish, no
        # paradox audit: those observability hooks fire on misses where
        # the work actually happened. Hits just short-circuit.
        cached = self._cache_get(task.agent, payload)
        if cached is not None:
            self._cache_hits += 1
            # Strip volatile fields without allocating a filtered dict
            task.result = cached
            if "paradox_audit" in cached or "_cached_at" in cached:
                task.result = {k: v for k, v in cached.items()
                               if k not in ("paradox_audit", "_cached_at")}
                task.result["_cache"] = "hit"
            else:
                task.result["_cache"] = "hit"
            task.status = "done"
            task.finished_at = task.started_at
            state.total_tasks_completed += 1
            return
        self._cache_misses += 1

        try:
            if hasattr(agent, "execute"):
                result = agent.execute(payload)
            elif hasattr(agent, "run"):
                result = agent.run(payload)
            else:
                result = {"status": "noop", "reason": "agent has no execute/run"}
            task.result = result if isinstance(result, dict) else {"result": str(result)}
            task.status = "done" if task.result.get("status") != "failed" else "failed"
            # Populate cache only on successful (non-failed) results.
            if task.status == "done":
                self._cache_put(task.agent, payload, task.result)
        except Exception as e:
            logger.exception("agent %s failed: %s", task.agent, e)
            task.status = "failed"
            task.error = str(e)
            healing = getattr(e, "_healing", None)
            if healing is None:
                try:
                    from learning.healing import handle_failure
                    healing = handle_failure(
                        e,
                        agent=task.agent,
                        task_id=task.task_id,
                        payload=payload,
                    )
                except Exception:
                    logger.debug("healing proposal failed", exc_info=True)
                    healing = None
            if healing:
                task.result = {"status": "failed", "error": task.error, "healing": healing}
        finally:
            task.finished_at = time.time()
            latency = (task.finished_at - task.started_at) if task.started_at else None
            if learner and task.agent:
                try:
                    learner.record_outcome(
                        task.agent,
                        success=(task.status == "done"),
                        error=task.error,
                        latency=latency,
                        context={"intent": task.intent, "task_id": task.task_id},
                    )
                    if state.total_tasks_completed % 10 == 0:
                        learner.auto_tune()
                except Exception:
                    logger.debug("learner record failed", exc_info=True)
            if record_trajectory:
                try:
                    record_trajectory(
                        task_id=task.task_id,
                        intent=task.intent,
                        agent=task.agent,
                        status=task.status,
                        payload=payload,
                        result=task.result if isinstance(task.result, dict) else None,
                        error=task.error,
                        started_at=task.started_at,
                        finished_at=task.finished_at,
                    )
                except Exception:
                    logger.debug("trajectory record failed", exc_info=True)
            state.total_tasks_completed += 1
            if bus:
                try:
                    bus.publish_sync("task.done", {"task_id": task.task_id, "status": task.status, "agent": task.agent}, source="orchestrator")
                except Exception:
                    pass

            # Paradox / brain audit now runs and augments result (affects downstream phrasing + logs)
            if paradox_auditor:
                try:
                    audit_ctx = {
                        "user_msg": payload.get("user_msg"),
                        "intent": task.intent,
                        "agent": task.agent,
                        "result": task.result,
                        "confidence": getattr(task, "confidence", 0.75),
                    }
                    audit = paradox_auditor.audit(audit_ctx)
                    if task.result and isinstance(task.result, dict):
                        task.result["paradox_audit"] = audit
                    else:
                        task.result = {"paradox_audit": audit}
                except Exception:
                    pass

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
        if learner and skill_name:
            try:
                latency = (task.finished_at - task.started_at) if task.started_at else None
                learner.record_outcome(
                    f"skill:{skill_name}",
                    success=(task.status == "done"),
                    error=task.error,
                    latency=latency,
                    context={"intent": task.intent},
                )
            except Exception:
                pass
        if record_trajectory:
            try:
                record_trajectory(
                    task_id=task.task_id,
                    intent=task.intent,
                    agent=f"skill:{skill_name}" if skill_name else task.agent,
                    status=task.status,
                    payload={**task.payload, "skill_name": skill_name},
                    result=task.result if isinstance(task.result, dict) else None,
                    error=task.error,
                    started_at=task.started_at,
                    finished_at=task.finished_at,
                )
            except Exception:
                pass
        state.total_tasks_completed += 1


# Single shared instance
orchestrator = Orchestrator()
