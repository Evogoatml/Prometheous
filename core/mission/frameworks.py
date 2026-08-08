"""
Framework stack for missions:

  SuperAGI  → decompose goal into subtasks
  CrewAI    → coordinate which specialist owns each subtask
  AgentGPT  → research / synthesis
  Agent K   → skills / ops / code-ish work
  Swarm AI  → parallel-execute a fleet of workers

These are the real "bots" the user asked for — not a single custom script.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from core.mission.fleet import parallel_workers


# Canonical framework ids ↔ agent/tile names
FRAMEWORKS = (
    "superagi",
    "crewai",
    "agentgpt",
    "agentk",
    "swarms",
)

FRAMEWORK_ALIASES = {
    "superagi": "superagi",
    "super agi": "superagi",
    "super-agi": "superagi",
    "crewai": "crewai",
    "crew ai": "crewai",
    "crew-ai": "crewai",
    "agentgpt": "agentgpt",
    "agent gpt": "agentgpt",
    "agent-gpt": "agentgpt",
    "agentk": "agentk",
    "agent k": "agentk",
    "agent-k": "agentk",
    "k": "agentk",
    "swarms": "swarms",
    "swarm": "swarms",
    "swarm ai": "swarms",
    "swarmai": "swarms",
}


def mentioned_frameworks(goal: str) -> List[str]:
    """Which frameworks the user named (order preserved)."""
    g = (goal or "").lower()
    found: List[str] = []
    # longer phrases first
    keys = sorted(FRAMEWORK_ALIASES.keys(), key=len, reverse=True)
    used_spans: List[Tuple[int, int]] = []
    for key in keys:
        idx = g.find(key)
        if idx < 0:
            continue
        # avoid overlapping double-counts
        end = idx + len(key)
        if any(not (end <= a or idx >= b) for a, b in used_spans):
            continue
        fid = FRAMEWORK_ALIASES[key]
        if fid not in found:
            found.append(fid)
            used_spans.append((idx, end))
    return found


def ensure_framework_agents() -> Dict[str, Any]:
    """
    Register CrewAI / SuperAGI / AgentGPT / AgentK / Swarms on the orchestrator
    (as real agents, not only tiles).
    """
    from core.orchestrator import orchestrator

    registered = {}
    loaders = {
        "superagi": ("agents.superagi_agent", "SuperAGIAgent"),
        "crewai": ("agents.crewai_agent", "CrewAISpecialist"),
        "agentgpt": ("agents.agentgpt_agent", "AgentGPTAgent"),
        "agentk": ("agents.agent_k", "AgentKExecutor"),
        "swarms": ("agents.swarms_agent", "SwarmsSpecialist"),
    }
    import importlib

    for name, (mod_path, cls_name) in loaders.items():
        existing = orchestrator.get_agent(name)
        if existing is not None:
            registered[name] = existing
            continue
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            inst = cls()
            # normalize .name for BaseAgent subclasses
            if not getattr(inst, "name", None) or getattr(inst, "name", "") == "base":
                try:
                    inst.name = name
                except Exception:
                    pass
            orchestrator.register_agent(name, inst)
            if hasattr(inst, "on_deploy"):
                try:
                    inst.on_deploy()
                except Exception:
                    pass
            registered[name] = inst
        except Exception as e:
            registered[name] = {"error": str(e)}
    return registered


def call_framework(name: str, goal: str, **extra: Any) -> Dict[str, Any]:
    """Execute one framework agent with a normalized payload."""
    ensure_framework_agents()
    from core.orchestrator import orchestrator

    agent = orchestrator.get_agent(name)
    if agent is None:
        return {"status": "failed", "agent": name, "error": "not registered"}

    payload = {
        "user_msg": goal,
        "query": goal,
        "goal": goal,
        "task": goal,
        "text": goal,
        **extra,
    }
    try:
        if hasattr(agent, "execute"):
            out = agent.execute(payload)
        elif hasattr(agent, "run"):
            out = agent.run(payload)
        else:
            return {"status": "failed", "agent": name, "error": "no execute"}
        if not isinstance(out, dict):
            out = {"status": "ok", "result": out}
        out.setdefault("agent", name)
        out.setdefault("status", "ok")
        # normalize formatted
        if not out.get("formatted"):
            msg = out.get("message") or out.get("error")
            if not msg and out.get("subtasks"):
                msg = f"SuperAGI: {len(out['subtasks'])} subtasks"
            if not msg and out.get("team_results") is not None:
                msg = out.get("message") or f"CrewAI team size {len(out.get('team') or [])}"
            if not msg:
                msg = f"{name} completed"
            out["formatted"] = str(msg)[:2000]
        return out
    except Exception as e:
        return {"status": "failed", "agent": name, "error": str(e)}


def run_framework_stack(
    goal: str,
    *,
    fleet_size: int = 1,
    frameworks: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Full stack pipeline:

      1. SuperAGI decomposes
      2. CrewAI coordinates team (agentgpt, agentk, + fleet)
      3. AgentGPT researches
      4. AgentK runs skill ops
      5. Swarms parallel-runs N workers on subtasks
    """
    ensure_framework_agents()
    stack = frameworks or list(FRAMEWORKS)
    steps: List[Dict[str, Any]] = []
    subtasks: List[Dict[str, Any]] = []
    artifacts: Dict[str, Any] = {}

    t0 = time.time()

    if "superagi" in stack:
        decomp = call_framework("superagi", goal)
        steps.append(
            {
                "framework": "superagi",
                "status": decomp.get("status"),
                "count": decomp.get("count") or len(decomp.get("subtasks") or []),
            }
        )
        subtasks = list(decomp.get("subtasks") or [])
        artifacts["superagi"] = decomp
        if not subtasks:
            # deterministic shards if decomposer empty
            subtasks = [
                {
                    "step": i + 1,
                    "description": f"{goal[:80]} [shard {i}]",
                    "agent": "swarms",
                }
                for i in range(max(1, fleet_size))
            ]

    if "agentgpt" in stack:
        research = call_framework("agentgpt", goal)
        steps.append({"framework": "agentgpt", "status": research.get("status")})
        artifacts["agentgpt"] = {
            "status": research.get("status"),
            "message": research.get("message") or research.get("formatted"),
            "used": research.get("used"),
        }

    if "agentk" in stack:
        skills = call_framework("agentk", goal)
        steps.append({"framework": "agentk", "status": skills.get("status")})
        artifacts["agentk"] = {
            "status": skills.get("status"),
            "message": skills.get("message") or skills.get("formatted"),
            "ops": len(skills.get("operations") or []),
        }

    if "crewai" in stack:
        crew = call_framework(
            "crewai",
            goal,
            subtasks=subtasks,
            team=["agentgpt", "agentk", "superagi", "swarms", "task", "web_search"],
        )
        steps.append(
            {
                "framework": "crewai",
                "status": crew.get("status"),
                "team": crew.get("team"),
            }
        )
        artifacts["crewai"] = {
            "status": crew.get("status"),
            "message": crew.get("message") or crew.get("formatted"),
            "team": crew.get("team"),
            "team_results_n": len(crew.get("team_results") or []),
        }

    swarm_out: Dict[str, Any] = {}
    if "swarms" in stack:
        # Expand subtasks to fleet_size if user asked for N bots
        work = subtasks
        if fleet_size > len(work):
            # pad by repeating / sharding
            padded = []
            for i in range(fleet_size):
                base = work[i % len(work)] if work else {
                    "step": i + 1,
                    "description": goal,
                    "agent": "worker",
                }
                padded.append(
                    {
                        **base,
                        "step": i + 1,
                        "shard": i,
                        "fleet_size": fleet_size,
                        "description": f"{base.get('description', goal)[:100]} [worker {i}]",
                    }
                )
            work = padded
        elif fleet_size > 1 and len(work) > fleet_size:
            work = work[:fleet_size]

        swarm_out = call_framework(
            "swarms",
            goal,
            subtasks=work,
            fleet_size=max(fleet_size, len(work)),
            workers=work,
        )
        steps.append(
            {
                "framework": "swarms",
                "status": swarm_out.get("status"),
                "parallel": swarm_out.get("parallel_workers"),
                "completed": swarm_out.get("completed"),
                "failed": swarm_out.get("failed"),
            }
        )
        artifacts["swarms"] = {
            "status": swarm_out.get("status"),
            "completed": swarm_out.get("completed"),
            "failed": swarm_out.get("failed"),
            "parallel_workers": swarm_out.get("parallel_workers"),
            "sample": (swarm_out.get("results") or [])[:5],
        }

    elapsed = time.time() - t0
    ok = all(
        s.get("status") in ("ok", "done", "degraded", None) for s in steps
    ) or any(s.get("status") == "ok" for s in steps)

    # How many "bots" effectively ran
    bots_ran = int(swarm_out.get("completed") or 0) + int(
        len(artifacts.get("crewai", {}).get("team") or [])
    )

    formatted_lines = [
        "🧠 Framework stack executed",
        "",
        f"Goal: {goal[:200]}",
        f"Stack: {' → '.join(stack)}",
        f"Fleet size target: {fleet_size}",
        f"Elapsed: {elapsed:.2f}s",
        "",
        "Framework results:",
    ]
    for s in steps:
        formatted_lines.append(
            f"  • {s.get('framework')}: {s.get('status')}"
            + (
                f" (parallel={s.get('parallel')}, ok={s.get('completed')}, fail={s.get('failed')})"
                if s.get("framework") == "swarms"
                else ""
            )
            + (f" subtasks={s.get('count')}" if s.get("count") else "")
        )

    if subtasks:
        formatted_lines.append("")
        formatted_lines.append(f"SuperAGI subtasks ({len(subtasks)}):")
        for st in subtasks[:12]:
            formatted_lines.append(
                f"  {st.get('step', '?')}. [{st.get('agent', '?')}] {st.get('description', '')[:100]}"
            )
        if len(subtasks) > 12:
            formatted_lines.append(f"  … +{len(subtasks) - 12} more")

    if swarm_out.get("results"):
        formatted_lines.append("")
        formatted_lines.append(
            f"Swarm workers finished: {swarm_out.get('completed')}/{swarm_out.get('fleet_size')}"
        )

    return {
        "status": "ok" if ok else "degraded",
        "agent": "framework_stack",
        "stack": stack,
        "fleet_size": fleet_size,
        "bots_ran": bots_ran,
        "subtasks": subtasks,
        "steps": steps,
        "artifacts": artifacts,
        "elapsed": elapsed,
        "formatted": "\n".join(formatted_lines),
    }
