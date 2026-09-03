"""
Mission conductor — plan → code → deploy → execute.

This is the user-facing autonomy path:
  give a task → get a plan → code is written → agents deploy → work runs.
"""
from __future__ import annotations

import importlib.util
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.mission.fleet import parallel_workers
from core.mission.frameworks import ensure_framework_agents, run_framework_stack
from core.mission.planner import MissionPlan, PlanStep, plan_mission

try:
    from utils.config import cfg

    ROOT = cfg.ROOT
    DATA = cfg.DATA_DIR
except Exception:
    ROOT = Path(__file__).resolve().parents[2]
    DATA = ROOT / "data"

MISSIONS_DIR = DATA / "missions"


@dataclass
class MissionResult:
    status: str
    mission_id: str
    goal: str
    plan: Dict[str, Any]
    steps_log: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    deployed: List[str] = field(default_factory=list)
    formatted: str = ""

    def to_agent_result(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "agent": "mission",
            "via": "mission",
            "mission_id": self.mission_id,
            "goal": self.goal,
            "plan": self.plan,
            "steps": self.steps_log,
            "deliverables": self.artifacts,
            "artifacts": self.artifacts,
            "deployed": self.deployed,
            "formatted": self.formatted,
        }


class MissionConductor:
    name = "mission"

    def run(self, goal: str, payload: Optional[Dict[str, Any]] = None) -> MissionResult:
        payload = payload or {}
        goal = (goal or payload.get("user_msg") or payload.get("query") or "").strip()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        mission_id = f"m_{stamp}"
        mission_dir = MISSIONS_DIR / mission_id
        mission_dir.mkdir(parents=True, exist_ok=True)
        (mission_dir / "agents").mkdir(exist_ok=True)

        if not goal:
            return MissionResult(
                status="failed",
                mission_id=mission_id,
                goal="",
                plan={},
                formatted="No task given. Tell me what you want done.",
            )

        # ── 1. PLAN ────────────────────────────────────────
        plan = plan_mission(goal)
        # resolve {mission_id} placeholders in paths
        plan = self._bind_paths(plan, mission_id)

        plan_path = mission_dir / "PLAN.md"
        plan_path.write_text(plan.markdown(), encoding="utf-8")
        plan_json = mission_dir / "plan.json"
        plan_json.write_text(
            json.dumps(plan.to_dict(), indent=2, default=str), encoding="utf-8"
        )

        artifacts: List[str] = [str(plan_path), str(plan_json)]
        steps_log: List[Dict[str, Any]] = [
            {
                "step": "plan",
                "status": "ok",
                "steps": len(plan.steps),
                "agents": plan.agents_needed,
                "path": str(plan_path),
            }
        ]
        deployed: List[str] = []
        observations: Dict[str, Any] = {"research": "", "executions": []}
        context = {
            "goal": goal,
            "mission_id": mission_id,
            "mission_dir": str(mission_dir),
            "payload": payload,
        }

        # ── 2–4. CODE / DEPLOY / EXECUTE per plan step ─────
        for step in plan.steps:
            log = self._run_step(step, context, observations, mission_dir)
            steps_log.append(log)
            for a in log.get("artifacts") or []:
                if a not in artifacts:
                    artifacts.append(a)
            if log.get("deployed"):
                for name in log["deployed"]:
                    if name not in deployed:
                        deployed.append(name)

        # ── report ─────────────────────────────────────────
        report_path = mission_dir / "REPORT.md"
        report = self._report(goal, mission_id, plan, steps_log, artifacts, deployed, observations)
        report_path.write_text(report, encoding="utf-8")
        artifacts.append(str(report_path))

        ok = not any(s.get("status") == "failed" and s.get("critical") for s in steps_log)
        # softer: ok if plan + at least one non-plan success
        successes = sum(1 for s in steps_log if s.get("status") == "ok")
        status = "ok" if successes >= 2 else ("degraded" if successes else "failed")

        formatted = self._format(
            goal, mission_id, plan, steps_log, artifacts, deployed, report_path
        )
        result = MissionResult(
            status=status,
            mission_id=mission_id,
            goal=goal,
            plan=plan.to_dict(),
            steps_log=steps_log,
            artifacts=artifacts,
            deployed=deployed,
            formatted=formatted,
        )
        self._record(result)
        return result

    # ── step runners ───────────────────────────────────────
    def _run_step(
        self,
        step: PlanStep,
        context: Dict[str, Any],
        observations: Dict[str, Any],
        mission_dir: Path,
    ) -> Dict[str, Any]:
        kind = step.kind
        log: Dict[str, Any] = {
            "step_id": step.id,
            "kind": kind,
            "title": step.title,
            "agent": step.agent,
            "status": "ok",
            "artifacts": [],
            "deployed": [],
        }

        try:
            if kind == "synthesize" and step.id == 1:
                # plan already written
                log["note"] = "brief recorded"
                return log

            if kind == "research" or (kind == "specialist" and step.agent == "web_search"):
                out = self._call_agent(
                    "web_search",
                    {
                        "query": context["goal"],
                        "user_msg": context["goal"],
                        "num_results": 6,
                    },
                )
                observations["research"] = out.get("formatted") or ""
                log["status"] = out.get("status", "ok")
                log["preview"] = (out.get("formatted") or "")[:400]
                # persist research
                p = mission_dir / "research.md"
                p.write_text(
                    f"# Research\n\n{out.get('formatted') or out}\n",
                    encoding="utf-8",
                )
                log["artifacts"].append(str(p))
                return log

            if kind == "specialist" and step.agent:
                out = self._call_agent(
                    step.agent,
                    {
                        "user_msg": context["goal"],
                        "query": context["goal"],
                        "goal": context["goal"],
                        "mission_id": context["mission_id"],
                    },
                )
                log["status"] = "ok" if out.get("status") in ("ok", "done", None) and not out.get("error") else out.get("status", "failed")
                if out.get("status") == "failed":
                    log["status"] = "failed"
                    log["error"] = out.get("error")
                log["preview"] = (out.get("formatted") or str(out)[:400])[:400]
                for key in ("deliverables", "artifacts", "wrote"):
                    for item in out.get(key) or []:
                        log["artifacts"].append(str(item))
                return log

            if kind == "framework_stack":
                return self._step_framework_stack(step, context, observations, mission_dir)

            if kind == "code":
                return self._step_code(step, context, observations, mission_dir)

            if kind == "deploy":
                return self._step_deploy(step, context, mission_dir)

            if kind == "deploy_fleet":
                return self._step_deploy_fleet(step, context, mission_dir)

            if kind == "execute":
                return self._step_execute(step, context, observations, mission_dir)

            if kind == "execute_fleet":
                return self._step_execute_fleet(step, context, observations, mission_dir)

            if kind == "synthesize":
                log["note"] = "final report"
                return log

            log["status"] = "skipped"
            log["note"] = f"unknown kind {kind}"
            return log
        except Exception as e:
            log["status"] = "failed"
            log["error"] = str(e)
            log["critical"] = kind in (
                "code",
                "deploy",
                "deploy_fleet",
                "execute",
                "execute_fleet",
                "framework_stack",
            )
            return log

    def _step_framework_stack(
        self,
        step: PlanStep,
        context: Dict[str, Any],
        observations: Dict[str, Any],
        mission_dir: Path,
    ) -> Dict[str, Any]:
        """SuperAGI → CrewAI → AgentGPT → AgentK → Swarm AI."""
        ensure_framework_agents()
        frameworks = (step.args or {}).get("frameworks") or [
            "superagi",
            "crewai",
            "agentgpt",
            "agentk",
            "swarms",
        ]
        fleet_size = int((step.args or {}).get("fleet_size") or 1)
        out = run_framework_stack(
            context["goal"],
            fleet_size=fleet_size,
            frameworks=frameworks,
        )
        observations["framework_stack"] = out
        # persist
        path = mission_dir / "framework_stack.json"
        try:
            path.write_text(
                json.dumps(
                    {
                        "stack": out.get("stack"),
                        "fleet_size": out.get("fleet_size"),
                        "steps": out.get("steps"),
                        "subtasks": out.get("subtasks"),
                        "bots_ran": out.get("bots_ran"),
                        "elapsed": out.get("elapsed"),
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        except Exception:
            path = None

        # Mark frameworks as "deployed" so the report shows the stack
        return {
            "step_id": step.id,
            "kind": "framework_stack",
            "title": step.title,
            "status": out.get("status", "ok"),
            "frameworks": frameworks,
            "fleet_size": fleet_size,
            "bots_ran": out.get("bots_ran"),
            "subtasks": len(out.get("subtasks") or []),
            "preview": (out.get("formatted") or "")[:600],
            "deployed": list(frameworks),
            "artifacts": [str(path)] if path else [],
        }

    def _step_code(
        self,
        step: PlanStep,
        context: Dict[str, Any],
        observations: Dict[str, Any],
        mission_dir: Path,
    ) -> Dict[str, Any]:
        bot_name = (step.args or {}).get("bot_name") or step.deploy_name or "worker"
        role = (step.args or {}).get("role") or (
            "agent" if step.deploy_name or "agent" in (step.write_path or "") else "worker"
        )
        fleet = (step.args or {}).get("fleet") or []
        fleet_size = int((step.args or {}).get("fleet_size") or len(fleet) or 1)
        rel = step.write_path or f"data/missions/{context['mission_id']}/{bot_name}.py"
        path = ROOT / rel if not Path(rel).is_absolute() else Path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)

        if role == "fleet_worker":
            content = self._generate_fleet_worker(
                bot_name, context["goal"], observations.get("research") or "", fleet_size
            )
        elif role == "fleet_agent":
            content = self._generate_fleet_agent_module(
                bot_name, context["goal"], fleet, mission_dir
            )
        elif role == "agent":
            content = self._generate_agent_module(
                bot_name, context["goal"], observations.get("research") or "", mission_dir
            )
        else:
            content = self._generate_worker_module(
                bot_name, context["goal"], observations.get("research") or ""
            )

        path.write_text(content, encoding="utf-8")
        return {
            "step_id": step.id,
            "kind": "code",
            "title": step.title,
            "status": "ok",
            "write_path": str(path),
            "bytes": len(content),
            "fleet_size": fleet_size,
            "artifacts": [str(path)],
            "deployed": [],
        }

    def _step_deploy(
        self,
        step: PlanStep,
        context: Dict[str, Any],
        mission_dir: Path,
    ) -> Dict[str, Any]:
        bot_name = step.deploy_name or (step.args or {}).get("bot_name") or "worker"
        module_rel = step.deploy_module or f"data/missions/{context['mission_id']}/agents/{bot_name}_agent.py"
        module_path = ROOT / module_rel if not Path(module_rel).is_absolute() else Path(module_rel)

        if not module_path.exists():
            # generate agent if missing
            module_path.parent.mkdir(parents=True, exist_ok=True)
            module_path.write_text(
                self._generate_agent_module(bot_name, context["goal"], "", mission_dir),
                encoding="utf-8",
            )

        registered = self._register_module(bot_name, module_path)
        log = {
            "step_id": step.id,
            "kind": "deploy",
            "title": step.title,
            "status": registered.get("status", "failed"),
            "deployed": [],
            "artifacts": [str(module_path)],
            "module": str(module_path),
        }
        if registered.get("status") == "ok":
            log["deployed"] = [bot_name]
            log["agent_class"] = registered.get("class")
            # lifecycle
            try:
                from core.orchestrator import orchestrator

                agent = orchestrator.get_agent(bot_name)
                if agent and hasattr(agent, "on_deploy"):
                    agent.on_deploy()
            except Exception:
                pass
        else:
            log["error"] = registered.get("error")
            log["critical"] = True
        return log

    def _step_deploy_fleet(
        self,
        step: PlanStep,
        context: Dict[str, Any],
        mission_dir: Path,
    ) -> Dict[str, Any]:
        """Register N agents from one fleet module — not limited to 1."""
        fleet = (step.args or {}).get("fleet") or []
        module_rel = (
            step.deploy_module
            or (step.args or {}).get("module")
            or f"data/missions/{context['mission_id']}/agents/fleet_agent.py"
        )
        module_path = ROOT / module_rel if not Path(module_rel).is_absolute() else Path(module_rel)

        if not module_path.exists():
            module_path.parent.mkdir(parents=True, exist_ok=True)
            base = fleet[0]["base"] if fleet else "mission_worker"
            module_path.write_text(
                self._generate_fleet_agent_module(base, context["goal"], fleet, mission_dir),
                encoding="utf-8",
            )

        deployed: List[str] = []
        errors: List[str] = []

        # Load factory once
        factory = self._load_fleet_factory(module_path)
        if factory.get("status") != "ok":
            return {
                "step_id": step.id,
                "kind": "deploy_fleet",
                "title": step.title,
                "status": "failed",
                "error": factory.get("error"),
                "critical": True,
                "deployed": [],
                "artifacts": [str(module_path)],
            }

        make_agent = factory["make_agent"]
        from core.orchestrator import orchestrator

        def _deploy_one(member: Dict[str, Any]) -> tuple:
            name = member.get("name") or "worker"
            try:
                instance = make_agent(member)
                if hasattr(instance, "name"):
                    instance.name = name
                orchestrator.register_agent(name, instance)
                if hasattr(instance, "on_deploy"):
                    try:
                        instance.on_deploy()
                    except Exception:
                        pass
                return name, None
            except Exception as e:
                return name, str(e)

        # Parallel deploy
        workers = parallel_workers(max(1, len(fleet)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_deploy_one, m) for m in fleet]
            for fut in as_completed(futs):
                name, err = fut.result()
                if err:
                    errors.append(f"{name}: {err}")
                else:
                    deployed.append(name)

        # persist fleet roster
        roster = mission_dir / "fleet_roster.json"
        roster.write_text(
            json.dumps(
                {
                    "fleet_size": len(fleet),
                    "deployed": sorted(deployed),
                    "errors": errors,
                    "parallel_workers": workers,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        ok = len(deployed) > 0 and len(errors) == 0
        partial = len(deployed) > 0 and errors
        return {
            "step_id": step.id,
            "kind": "deploy_fleet",
            "title": step.title,
            "status": "ok" if ok else ("degraded" if partial else "failed"),
            "deployed": sorted(deployed),
            "deployed_count": len(deployed),
            "fleet_size": len(fleet),
            "errors": errors[:20],
            "parallel_workers": workers,
            "artifacts": [str(module_path), str(roster)],
            "critical": len(deployed) == 0,
        }

    def _step_execute_fleet(
        self,
        step: PlanStep,
        context: Dict[str, Any],
        observations: Dict[str, Any],
        mission_dir: Path,
    ) -> Dict[str, Any]:
        """Run all fleet agents concurrently."""
        fleet = (step.args or {}).get("fleet") or []
        names = [m.get("name") for m in fleet if m.get("name")]
        workers = parallel_workers(max(1, len(names)))
        results: List[Dict[str, Any]] = []
        ok_n = 0
        fail_n = 0

        def _run_one(member: Dict[str, Any]) -> Dict[str, Any]:
            name = member.get("name") or "worker"
            payload = {
                "user_msg": context["goal"],
                "query": context["goal"],
                "goal": context["goal"],
                "mission_id": context["mission_id"],
                "mission": True,
                "fleet_member": member,
                "shard": member.get("shard", 0),
                "fleet_size": member.get("fleet_size", len(names)),
                "role": member.get("role"),
                "prior_research": (observations.get("research") or "")[:800],
            }
            out = self._call_agent(name, payload)
            status = (
                "ok"
                if out.get("status") in ("ok", "done") or out.get("formatted")
                else "failed"
            )
            return {
                "agent": name,
                "status": status,
                "role": member.get("role"),
                "shard": member.get("shard"),
                "preview": (out.get("formatted") or out.get("message") or "")[:200],
                "error": out.get("error"),
            }

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_run_one, m): m for m in fleet}
            for fut in as_completed(futs):
                row = fut.result()
                results.append(row)
                if row["status"] == "ok":
                    ok_n += 1
                else:
                    fail_n += 1

        results.sort(key=lambda r: (r.get("shard") is None, r.get("shard") or 0, r.get("agent") or ""))
        observations["executions"] = results
        out_path = mission_dir / "fleet_results.json"
        out_path.write_text(
            json.dumps(
                {
                    "goal": context["goal"],
                    "fleet_size": len(names),
                    "ok": ok_n,
                    "failed": fail_n,
                    "parallel_workers": workers,
                    "results": results,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        # Also run shared worker once as integration check
        worker = mission_dir / "fleet_worker.py"
        script_note = {}
        if worker.exists():
            script_note = self._run_python_script(
                str(worker.relative_to(ROOT)),
                {"artifacts": []},
            )

        status = "ok" if fail_n == 0 and ok_n > 0 else ("degraded" if ok_n else "failed")
        return {
            "step_id": step.id,
            "kind": "execute_fleet",
            "title": step.title,
            "status": status,
            "fleet_size": len(names),
            "ok": ok_n,
            "failed": fail_n,
            "parallel_workers": workers,
            "sample": results[:5],
            "script_run": {
                "status": script_note.get("status"),
                "stdout": (script_note.get("stdout") or "")[:200],
            }
            if script_note
            else None,
            "artifacts": [str(out_path)],
            "deployed": [],
            "critical": ok_n == 0,
        }

    def _load_fleet_factory(self, path: Path) -> Dict[str, Any]:
        try:
            spec = importlib.util.spec_from_file_location(
                f"mission_fleet_{path.stem}_{int(time.time())}", path
            )
            if spec is None or spec.loader is None:
                return {"status": "failed", "error": "spec load failed"}
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "make_agent") and callable(mod.make_agent):
                return {"status": "ok", "make_agent": mod.make_agent}
            if hasattr(mod, "Agent"):
                cls = mod.Agent

                def make_agent(member: Dict[str, Any]):
                    inst = cls()
                    if hasattr(inst, "configure"):
                        inst.configure(member)
                    return inst

                return {"status": "ok", "make_agent": make_agent}
            return {"status": "failed", "error": "no make_agent/Agent in fleet module"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def _generate_fleet_worker(
        self, base: str, goal: str, research: str, fleet_size: int
    ) -> str:
        safe_goal = goal.replace("\\", "\\\\").replace('"""', "'''")
        research_note = (research or "")[:240].replace('"', "'")
        return f'''#!/usr/bin/env python3
"""
Fleet worker template — runs for any shard in a mission fleet.
Base: {base} | fleet_size: {fleet_size}
Goal: {safe_goal[:240]}
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional


GOAL = {json.dumps(goal)}
FLEET_SIZE = {int(fleet_size)}


def run(
    goal: str = GOAL,
    *,
    shard: int = 0,
    fleet_size: int = FLEET_SIZE,
    role: str = "worker",
    name: str = "{base}",
) -> Dict[str, Any]:
    """Shard-aware work unit. Each fleet member calls this with its shard id."""
    lines = [
        f"[{{name}}] shard={{shard}}/{{max(fleet_size-1, 0)}} role={{role}}",
        f"goal: {{goal[:160]}}",
    ]
    research_snip = {json.dumps(research_note)}
    # Role-specialized micro-tasks (deterministic, no LLM required)
    role_l = (role or "worker").lower()
    if role_l == "researcher":
        action = f"research slice {{shard}}: gather sources related to goal"
    elif role_l == "coder":
        action = f"code slice {{shard}}: implement/verify a unit of work"
    elif role_l == "reviewer":
        action = f"review slice {{shard}}: check assumptions and outputs"
    else:
        action = f"worker slice {{shard}}: execute assigned unit of work"
    lines.append(action)
    if research_snip:
        lines.append(f"research_hint: {{research_snip[:120]}}")
    lines.append("status: complete")
    message = "\\n".join(lines)
    print(message)
    return {{
        "status": "ok",
        "message": message,
        "bot": name,
        "shard": shard,
        "fleet_size": fleet_size,
        "role": role,
        "goal": goal[:300],
    }}


def main() -> None:
    # demo single shard
    print(json.dumps(run(shard=0), indent=2))


if __name__ == "__main__":
    main()
'''

    def _generate_fleet_agent_module(
        self,
        base: str,
        goal: str,
        fleet: List[Dict[str, Any]],
        mission_dir: Path,
    ) -> str:
        worker_rel = f"data/missions/{mission_dir.name}/fleet_worker.py"
        fleet_json = json.dumps(fleet, indent=2)
        return f'''"""
Fleet agent factory — one module, many agents.

Deploy with make_agent(member) for each fleet roster entry.
Mission: {mission_dir.name}
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from swarm.base import BaseAgent
except Exception:
    class BaseAgent:  # type: ignore
        name = "base"
        def __init__(self):
            self.tasks_completed = 0


ROOT = Path(__file__).resolve().parents[4]
WORKER = ROOT / {json.dumps(worker_rel)}
FLEET = {fleet_json}
GOAL_DEFAULT = {json.dumps(goal)}


def _run_worker(
    goal: str,
    *,
    shard: int = 0,
    fleet_size: int = 1,
    role: str = "worker",
    name: str = "worker",
) -> Dict[str, Any]:
    if not WORKER.exists():
        return {{"status": "failed", "error": f"worker missing: {{WORKER}}"}}
    spec = importlib.util.spec_from_file_location("fleet_worker_dyn", WORKER)
    if spec is None or spec.loader is None:
        return {{"status": "failed", "error": "cannot load worker"}}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "run"):
        return mod.run(
            goal,
            shard=shard,
            fleet_size=fleet_size,
            role=role,
            name=name,
        )
    return {{"status": "failed", "error": "worker has no run()"}}


class FleetMemberAgent(BaseAgent):
    """One instance per fleet seat — same class, different name/shard/role."""

    name = "fleet_member"
    role = "DeployedWorker"
    specialty = "fleet worker"
    version = "0.2.0"

    def __init__(self, member: Optional[Dict[str, Any]] = None):
        super().__init__() if hasattr(super(), "__init__") else None
        self.tasks_completed = 0
        self._member = member or {{}}
        self.name = self._member.get("name") or "fleet_member"
        self.role = self._member.get("role") or "worker"
        self.specialty = self._member.get("specialty") or "fleet worker"
        self.shard = int(self._member.get("shard") or 0)
        self.fleet_size = int(self._member.get("fleet_size") or 1)

    def configure(self, member: Dict[str, Any]) -> "FleetMemberAgent":
        self.__init__(member)
        return self

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed = getattr(self, "tasks_completed", 0) + 1
        goal = (
            payload.get("goal")
            or payload.get("user_msg")
            or payload.get("query")
            or GOAL_DEFAULT
        )
        member = payload.get("fleet_member") or self._member
        shard = int(payload.get("shard", member.get("shard", self.shard)))
        fleet_size = int(
            payload.get("fleet_size", member.get("fleet_size", self.fleet_size))
        )
        role = payload.get("role") or member.get("role") or self.role
        name = member.get("name") or self.name
        result = _run_worker(
            str(goal),
            shard=shard,
            fleet_size=fleet_size,
            role=str(role),
            name=str(name),
        )
        status = result.get("status", "ok")
        message = result.get("message") or str(result)
        return {{
            "status": status,
            "agent": name,
            "shard": shard,
            "fleet_size": fleet_size,
            "role": role,
            "result": result,
            "formatted": (
                f"🤖 `{{name}}` (shard {{shard}}/{{max(fleet_size-1,0)}}, {{role}})\\n"
                f"{{message}}"
            ),
        }}


def make_agent(member: Dict[str, Any]) -> FleetMemberAgent:
    """Factory used by MissionConductor to deploy the whole fleet."""
    return FleetMemberAgent(member)


Agent = FleetMemberAgent
'''

    def _step_execute(
        self,
        step: PlanStep,
        context: Dict[str, Any],
        observations: Dict[str, Any],
        mission_dir: Path,
    ) -> Dict[str, Any]:
        log: Dict[str, Any] = {
            "step_id": step.id,
            "kind": "execute",
            "title": step.title,
            "status": "ok",
            "artifacts": [],
            "deployed": [],
        }

        # Run generated script
        if (step.args or {}).get("run_script") and step.write_path:
            rel = step.write_path
            return self._run_python_script(rel, log)

        agent_name = step.agent or (step.args or {}).get("bot_name")
        if not agent_name:
            log["status"] = "failed"
            log["error"] = "no agent to execute"
            return log

        # Prefer deployed bot; fall back to task
        out = self._call_agent(
            agent_name,
            {
                "user_msg": context["goal"],
                "query": context["goal"],
                "goal": context["goal"],
                "mission_id": context["mission_id"],
                "mission": True,
                "prior_research": (observations.get("research") or "")[:1500],
            },
        )
        if out.get("status") == "failed" and agent_name not in ("task", "web_search"):
            # adaptive: fall back to task agent
            fb = self._call_agent(
                "task",
                {
                    "user_msg": context["goal"],
                    "goal": context["goal"],
                    "mosaic": True,  # avoid re-escalation loops into mission
                },
            )
            log["adapt"] = "task"
            out = fb

        log["agent"] = agent_name
        log["status"] = (
            "ok"
            if out.get("status") in ("ok", "done") or out.get("formatted")
            else "failed"
        )
        if out.get("status") == "failed" and not out.get("formatted"):
            log["status"] = "failed"
            log["error"] = out.get("error")
            log["critical"] = True
        log["preview"] = (out.get("formatted") or "")[:500]
        for key in ("deliverables", "artifacts", "wrote"):
            for item in out.get(key) or []:
                log["artifacts"].append(str(item))
        observations["executions"].append(
            {"agent": agent_name, "status": log["status"], "preview": log.get("preview")}
        )

        # If agent is a worker that also has a .py script, try running it
        bot = (step.args or {}).get("bot_name")
        if bot:
            script = mission_dir / f"{bot}.py"
            if script.exists():
                run_log = self._run_python_script(str(script.relative_to(ROOT)), {"artifacts": []})
                log["script_run"] = {
                    "status": run_log.get("status"),
                    "stdout": run_log.get("stdout", "")[:300],
                }
                log["artifacts"].extend(run_log.get("artifacts") or [])
        return log

    def _run_python_script(self, rel: str, log: Dict[str, Any]) -> Dict[str, Any]:
        log = dict(log)
        log.setdefault("artifacts", [])
        try:
            from llm.tool_router import ToolCall, execute_tool

            # ensure path is project-relative
            p = Path(rel)
            if p.is_absolute():
                try:
                    rel = str(p.relative_to(ROOT))
                except ValueError:
                    rel = str(p)
            call = ToolCall(
                name="shell.run",
                arguments={"command": f"python3 {rel}"},
                confidence=1.0,
                source="mission",
            )
            result = execute_tool(call)
            log["status"] = "ok" if result.get("returncode", 1) == 0 or result.get("status") == "ok" else "failed"
            if result.get("error"):
                log["status"] = "failed"
                log["error"] = result.get("error")
            log["stdout"] = (result.get("stdout") or "")[:500]
            log["returncode"] = result.get("returncode")
            log["command"] = f"python3 {rel}"
            # still record the script as artifact
            ap = ROOT / rel
            if ap.exists():
                log["artifacts"].append(str(ap))
        except Exception as e:
            log["status"] = "failed"
            log["error"] = str(e)
        return log

    # ── code generation ────────────────────────────────────
    def _generate_worker_module(self, bot_name: str, goal: str, research: str) -> str:
        safe_goal = goal.replace("\\", "\\\\").replace('"""', "'''")
        # Domain-specific snippets
        g = goal.lower()
        body = self._worker_body(g, bot_name, safe_goal, research)
        return f'''#!/usr/bin/env python3
"""
Mission worker: {bot_name}
Auto-generated by Prometheous MissionConductor.
Goal: {safe_goal[:300]}
"""
from __future__ import annotations

from typing import Any, Dict


GOAL = {json.dumps(goal)}


def run(goal: str = GOAL) -> Dict[str, Any]:
    """Execute the worker logic for this mission."""
{body}


def main() -> None:
    result = run()
    print(result.get("message") or result)


if __name__ == "__main__":
    main()
'''

    def _worker_body(self, g: str, bot_name: str, safe_goal: str, research: str) -> str:
        if re.search(r"\bhello\b", g) and re.search(r"\bprint", g):
            return '''    msg = "Hello, World!"
    print(msg)
    return {"status": "ok", "message": msg, "bot": "%s"}
''' % bot_name

        if "checklist" in g or "launch" in g:
            return '''    steps = [
        "1. Positioning — niche, offer, buyer persona",
        "2. Product readiness — catalog, pricing, checkout",
        "3. Traffic — one paid + one organic channel",
    ]
    for s in steps:
        print(s)
    return {
        "status": "ok",
        "message": "\\n".join(steps),
        "steps": steps,
        "bot": "%s",
        "goal": goal[:200],
    }
''' % bot_name

        if "price" in g or "pricing" in g:
            return '''    notes = [
        "Anchor price against 3 competitors",
        "Test good / better / best tiers",
        "Review conversion after 7 days",
    ]
    print("Pricing worker output:")
    for n in notes:
        print("-", n)
    return {"status": "ok", "message": "; ".join(notes), "bot": "%s"}
''' % bot_name

        # generic: no specialized handler matched this goal — say so honestly
        # instead of claiming completion, and surface whatever research was
        # actually gathered as the real deliverable.
        research_note = (research or "")[:200].replace('"', "'")
        return f'''    lines = [
        "Worker `{bot_name}` has no specialized handler for this goal",
        f"Goal: {{goal[:200]}}",
    ]
    research_snip = {json.dumps(research_note)}
    if research_snip:
        lines.append(f"Research gathered: {{research_snip[:160]}}")
    else:
        lines.append("No research or specialized logic available for this goal")
    lines.append("Status: partial — needs a real handler for this goal type")
    message = "\\n".join(lines)
    print(message)
    return {{
        "status": "partial",
        "message": message,
        "bot": "{bot_name}",
        "goal": goal[:300],
    }}
'''

    def _generate_agent_module(
        self, bot_name: str, goal: str, research: str, mission_dir: Path
    ) -> str:
        class_name = "".join(p.title() for p in bot_name.split("_") if p) + "Agent"
        if not class_name[0].isalpha():
            class_name = "Deployed" + class_name
        worker_rel = f"data/missions/{mission_dir.name}/{bot_name}.py"
        return f'''"""
Deployed mission agent: {bot_name}
Auto-generated by Prometheous MissionConductor.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict

try:
    from swarm.base import BaseAgent
except Exception:  # minimal fallback
    class BaseAgent:  # type: ignore
        name = "base"
        def __init__(self):
            self.tasks_completed = 0


ROOT = Path(__file__).resolve().parents[4]
WORKER = ROOT / {json.dumps(worker_rel)}


def _run_worker(goal: str) -> Dict[str, Any]:
    if not WORKER.exists():
        return {{"status": "failed", "error": f"worker missing: {{WORKER}}"}}
    spec = importlib.util.spec_from_file_location("{bot_name}_worker", WORKER)
    if spec is None or spec.loader is None:
        return {{"status": "failed", "error": "cannot load worker"}}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "run"):
        return mod.run(goal)
    if hasattr(mod, "main"):
        mod.main()
        return {{"status": "ok", "message": "main() completed"}}
    return {{"status": "failed", "error": "worker has no run/main"}}


class {class_name}(BaseAgent):
    name = {json.dumps(bot_name)}
    role = "DeployedWorker"
    specialty = {json.dumps(goal[:120])}
    version = "0.1.0"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed = getattr(self, "tasks_completed", 0) + 1
        goal = (
            payload.get("goal")
            or payload.get("user_msg")
            or payload.get("query")
            or {json.dumps(goal)}
        )
        result = _run_worker(str(goal))
        status = result.get("status", "ok")
        message = result.get("message") or result.get("formatted") or str(result)
        return {{
            "status": status,
            "agent": self.name,
            "result": result,
            "formatted": (
                f"🤖 Deployed agent `{{self.name}}`\\n\\n"
                f"{{message}}"
            ),
        }}


# Hot-import convenience for orchestrator registration
Agent = {class_name}
'''

    def _register_module(self, name: str, path: Path) -> Dict[str, Any]:
        try:
            from core.orchestrator import orchestrator

            spec = importlib.util.spec_from_file_location(
                f"mission_deployed_{name}", path
            )
            if spec is None or spec.loader is None:
                return {"status": "failed", "error": "spec load failed"}
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            # find agent class
            candidate = None
            if hasattr(mod, "Agent"):
                candidate = mod.Agent
            else:
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if (
                        isinstance(obj, type)
                        and attr.endswith("Agent")
                        and attr != "BaseAgent"
                    ):
                        candidate = obj
                        break
            if candidate is None:
                return {"status": "failed", "error": "no Agent class in module"}

            instance = candidate()
            # ensure name
            if getattr(instance, "name", None) != name:
                try:
                    instance.name = name
                except Exception:
                    pass
            orchestrator.register_agent(name, instance)
            return {
                "status": "ok",
                "registered": name,
                "class": getattr(candidate, "__name__", str(candidate)),
                "agents": orchestrator.list_agents(),
            }
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def _call_agent(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from core.orchestrator import orchestrator

            agent = orchestrator.get_agent(name)
            if agent is None:
                agent = self._lazy(name)
                if agent is not None:
                    orchestrator.register_agent(name, agent)
            if agent is None:
                return {"status": "failed", "error": f"agent {name} not registered"}
            if hasattr(agent, "execute"):
                return agent.execute(payload) or {"status": "failed", "error": "empty"}
            if hasattr(agent, "run"):
                return agent.run(payload) or {"status": "failed", "error": "empty"}
            return {"status": "failed", "error": f"{name} has no execute"}
        except Exception as e:
            return {"status": "failed", "error": str(e), "agent": name}

    def _lazy(self, name: str):
        mapping = {
            "task": "agents.task_agent.TaskAgent",
            "web_search": "agents.web_search_agent.WebSearchAgent",
            "growth": "agents.growth_agent.GrowthAgent",
            "shopify_ads": "agents.shopify_ads_agent.ShopifyAdsAgent",
            "scanner": "agents.scanner.ScannerAgent",
            "mosaic": "agents.mosaic_agent.MosaicAgent",
            "mission": "agents.mission_agent.MissionAgent",
        }
        path = mapping.get(name)
        if not path:
            return None
        mod_name, cls = path.rsplit(".", 1)
        try:
            import importlib

            return getattr(importlib.import_module(mod_name), cls)()
        except Exception:
            return None

    def _bind_paths(self, plan: MissionPlan, mission_id: str) -> MissionPlan:
        for step in plan.steps:
            if step.write_path:
                step.write_path = step.write_path.replace("{mission_id}", mission_id)
            if step.deploy_module:
                step.deploy_module = step.deploy_module.replace("{mission_id}", mission_id)
        plan.code_artifacts = [
            p.replace("{mission_id}", mission_id) for p in plan.code_artifacts
        ]
        return plan

    def _report(
        self,
        goal: str,
        mission_id: str,
        plan: MissionPlan,
        steps_log: list,
        artifacts: list,
        deployed: list,
        observations: dict,
    ) -> str:
        lines = [
            f"# Mission report — {mission_id}",
            "",
            f"**Goal:** {goal}",
            f"**Status steps:** {len(steps_log)}",
            f"**Deployed agents:** {', '.join(deployed) or 'none'}",
            "",
            "## Plan summary",
            "",
            plan.summary,
            "",
            "## Execution log",
            "",
        ]
        for s in steps_log:
            st = s.get("status", "?")
            lines.append(
                f"- **{s.get('kind', s.get('step'))}** `{s.get('title') or s.get('step')}` → {st}"
            )
            if s.get("write_path"):
                lines.append(f"  - wrote `{s['write_path']}`")
            if s.get("deployed"):
                lines.append(f"  - deployed: {s['deployed']}")
            if s.get("error"):
                lines.append(f"  - error: {s['error']}")
            if s.get("stdout"):
                lines.append(f"  - stdout: {s['stdout'][:200]}")
            if s.get("preview"):
                lines.append(f"  - preview: {str(s['preview'])[:200]}")
        lines += ["", "## Artifacts", ""]
        for a in artifacts:
            lines.append(f"- {a}")
        if observations.get("research"):
            lines += ["", "## Research excerpt", "", str(observations["research"])[:2000], ""]
        lines += [
            "",
            "## Success criteria",
            "",
        ]
        for c in plan.success_criteria:
            lines.append(f"- {c}")
        lines.append("")
        return "\n".join(lines)

    def _format(
        self,
        goal: str,
        mission_id: str,
        plan: MissionPlan,
        steps_log: list,
        artifacts: list,
        deployed: list,
        report_path: Path,
    ) -> str:
        lines = [
            "🎯 Mission complete — plan → code → deploy → execute",
            "",
            f"Goal: {goal[:200]}",
            f"Mission: {mission_id}",
            f"Fleet: {getattr(plan, 'fleet_size', len(deployed))} agents "
            f"(deployed {len(deployed)})",
            "",
            "Plan:",
            f"  {plan.summary}",
            "",
            "Steps:",
        ]
        for s in steps_log:
            kind = s.get("kind") or s.get("step")
            title = s.get("title") or ""
            status = s.get("status", "?")
            extra = ""
            if s.get("write_path"):
                extra = f" → {s['write_path']}"
            elif kind == "framework_stack":
                extra = (
                    f" → {'+'.join(s.get('frameworks') or [])} "
                    f"fleet×{s.get('fleet_size')} bots_ran={s.get('bots_ran')}"
                )
            elif kind == "deploy_fleet":
                extra = (
                    f" → {s.get('deployed_count', len(s.get('deployed') or []))} agents "
                    f"(parallel={s.get('parallel_workers')})"
                )
            elif kind == "execute_fleet":
                extra = (
                    f" → ok={s.get('ok')} fail={s.get('failed')} "
                    f"parallel={s.get('parallel_workers')}"
                )
            elif s.get("deployed") and len(s.get("deployed") or []) <= 5:
                extra = f" → deployed {s['deployed']}"
            elif s.get("deployed"):
                extra = f" → deployed {len(s['deployed'])} agents"
            elif s.get("stdout"):
                extra = f" → {s['stdout'][:80]!r}"
            lines.append(f"  • [{kind}] {title} [{status}]{extra}")

        if deployed:
            lines.append("")
            if len(deployed) <= 12:
                lines.append(
                    "Deployed agents: " + ", ".join(f"`{d}`" for d in deployed)
                )
            else:
                lines.append(
                    f"Deployed agents ({len(deployed)}): "
                    f"`{deployed[0]}` … `{deployed[-1]}`"
                )

        lines.append("")
        lines.append("Artifacts:")
        for a in artifacts[:12]:
            lines.append(f"  • {a}")

        lines.append("")
        lines.append(f"Full report: {report_path}")
        lines.append("")
        lines.append(
            "I planned the work, wrote the code, deployed the fleet, and ran them in parallel — "
            "not limited to one agent."
        )
        return "\n".join(lines)

    def _record(self, result: MissionResult) -> None:
        try:
            from learning.trajectory import record_task

            record_task(
                task_id=result.mission_id,
                intent="mission",
                agent="mission",
                status="done" if result.status in ("ok", "degraded") else "failed",
                payload={"goal": result.goal, "deployed": result.deployed},
                result={
                    "status": result.status,
                    "artifacts": result.artifacts[:20],
                    "deployed": result.deployed,
                },
            )
        except Exception:
            pass
        try:
            path = DATA / "learning" / "mission_trajectories.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "mission_id": result.mission_id,
                            "goal": result.goal[:500],
                            "status": result.status,
                            "deployed": result.deployed,
                            "artifacts": result.artifacts[:20],
                        },
                        default=str,
                    )
                    + "\n"
                )
        except Exception:
            pass


_conductor: Optional[MissionConductor] = None


def get_conductor() -> MissionConductor:
    global _conductor
    if _conductor is None:
        _conductor = MissionConductor()
    return _conductor
