"""
Mosaic runtime — assemble tiles, execute with shared blackboard, adapt, synthesize.

This is the polymorphic auto-mosaic loop:

  goal → assemble tiles (auto)
       → morph each tile with cognitive role (polymorphic)
       → execute via agents/tools (agentic)
       → on failure re-route (adaptive)
       → fuse outputs + write artifact + trajectory (gen / synthetic learning)
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.mosaic.blackboard import Blackboard
from core.mosaic.tiles import TileSpec, cognitive_constraints, select_tiles

try:
    from utils.config import cfg

    ROOT = cfg.ROOT
    DATA = cfg.DATA_DIR
except Exception:
    ROOT = Path(__file__).resolve().parents[2]
    DATA = ROOT / "data"

MOSAIC_DIR = DATA / "mosaic"
TRAJECTORY_EXTRA = DATA / "learning" / "mosaic_trajectories.jsonl"


@dataclass
class MosaicResult:
    status: str
    goal: str
    tiles: List[str]
    steps: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    formatted: str = ""
    blackboard: Optional[Dict[str, Any]] = None
    assembly_id: str = ""

    def to_agent_result(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "agent": "mosaic",
            "via": "mosaic",
            "goal": self.goal,
            "tiles": self.tiles,
            "steps": self.steps,
            "deliverables": self.artifacts,
            "artifacts": self.artifacts,
            "assembly_id": self.assembly_id,
            "formatted": self.formatted,
            "blackboard": self.blackboard,
        }


class MosaicRuntime:
    """Polymorphic auto-mosaic agentic runtime."""

    name = "mosaic"

    def __init__(self, max_tiles: int = 5):
        self.max_tiles = max_tiles
        self._last: Optional[MosaicResult] = None

    def assemble(self, goal: str) -> List[TileSpec]:
        return select_tiles(goal, max_tiles=self.max_tiles)

    def run(self, goal: str, payload: Optional[Dict[str, Any]] = None) -> MosaicResult:
        goal = (goal or "").strip()
        payload = payload or {}
        assembly_id = f"mosaic_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        bb = Blackboard(goal=goal)
        bb.meta["assembly_id"] = assembly_id
        bb.meta["payload_keys"] = list(payload.keys())

        tiles = self.assemble(goal)
        steps: List[Dict[str, Any]] = [
            {
                "step": "assemble",
                "tiles": [
                    {
                        "name": t.name,
                        "role": t.role,
                        "agent": t.agent,
                        "priority": t.priority,
                    }
                    for t in tiles
                ],
            }
        ]

        if not goal:
            return MosaicResult(
                status="failed",
                goal="",
                tiles=[],
                steps=steps,
                formatted="Empty goal — mosaic cannot assemble.",
                assembly_id=assembly_id,
            )

        for tile in tiles:
            step = self._run_tile(tile, bb, payload)
            steps.append(step)
            # Adaptive re-route: if primary agent failed, try task agent once
            if step.get("status") == "failed" and tile.agent and tile.agent != "task":
                alt = self._run_agent("task", goal, payload, bb, role=tile.role)
                steps.append(
                    {
                        "step": "adapt",
                        "from": tile.name,
                        "to": "task",
                        "status": alt.get("status"),
                    }
                )
                if alt.get("status") == "ok":
                    bb.write(f"{tile.name}_adapted", alt)
                    self._collect_artifacts(alt, bb)

        # Always ensure an artifact for synthetic learning + user value
        if not bb.artifacts:
            path = self._write_synthesis(goal, bb, tiles, force=True)
            if path:
                bb.add_artifact(path)
                steps.append({"step": "force_artifact", "path": path})

        formatted = self._format(goal, tiles, steps, bb)
        result = MosaicResult(
            status="ok" if not bb.errors or bb.artifacts else "degraded",
            goal=goal,
            tiles=[t.name for t in tiles],
            steps=steps,
            artifacts=list(bb.artifacts),
            formatted=formatted,
            blackboard=bb.snapshot(),
            assembly_id=assembly_id,
        )
        self._record_trajectory(result)
        self._last = result
        return result

    # ── tile execution ─────────────────────────────────────
    def _run_tile(
        self, tile: TileSpec, bb: Blackboard, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        constraints = cognitive_constraints(tile.role)
        bb.meta[f"constraints_{tile.name}"] = constraints[:200]

        if tile.executor == "synthesize":
            path = self._write_synthesis(bb.goal, bb, [tile])
            if path:
                bb.add_artifact(path)
            return {
                "step": "tile",
                "tile": tile.name,
                "role": tile.role,
                "status": "ok" if path else "failed",
                "path": path,
                "polymorph": tile.role,
            }

        if tile.executor == "task_write" or tile.name == "code":
            out = self._run_agent("task", bb.goal, payload, bb, role=tile.role)
            status = out.get("status", "failed")
            if status == "ok":
                bb.write(tile.name, out)
                self._collect_artifacts(out, bb)
            else:
                bb.fail(tile.name, str(out.get("error") or status))
            return {
                "step": "tile",
                "tile": tile.name,
                "role": tile.role,
                "agent": "task",
                "status": status,
                "polymorph": tile.role,
            }

        if tile.agent:
            out = self._run_agent(tile.agent, bb.goal, payload, bb, role=tile.role)
            status = out.get("status", "failed")
            if status in ("ok", "done") or out.get("formatted"):
                # treat useful formatted output as success even if status odd
                if status not in ("ok", "done"):
                    status = "ok"
                bb.write(tile.name, out)
                self._collect_artifacts(out, bb)
            else:
                bb.fail(tile.name, str(out.get("error") or status))
            return {
                "step": "tile",
                "tile": tile.name,
                "role": tile.role,
                "agent": tile.agent,
                "status": status,
                "polymorph": tile.role,
            }

        return {
            "step": "tile",
            "tile": tile.name,
            "status": "skipped",
            "reason": "no agent",
        }

    def _run_agent(
        self,
        name: str,
        goal: str,
        payload: Dict[str, Any],
        bb: Blackboard,
        *,
        role: str,
    ) -> Dict[str, Any]:
        try:
            from core.orchestrator import orchestrator

            agent = orchestrator.get_agent(name)
            if agent is None:
                agent = self._lazy_agent(name)
                if agent is not None:
                    orchestrator.register_agent(name, agent)
            if agent is None:
                return {"status": "failed", "error": f"agent {name} not registered"}

            # Polymorphic payload: inject cognitive role + prior research
            pl = {
                **payload,
                "user_msg": goal,
                "query": goal,
                "target": goal,
                "goal": goal,
                "mosaic_role": role,
                "cognitive_constraints": cognitive_constraints(role),
                "prior_research": bb.research_text()[:1500],
                "mosaic": True,
            }
            if hasattr(agent, "execute"):
                return agent.execute(pl) or {"status": "failed", "error": "empty"}
            if hasattr(agent, "run"):
                return agent.run(pl) or {"status": "failed", "error": "empty"}
            return {"status": "failed", "error": f"agent {name} has no execute/run"}
        except Exception as e:
            return {"status": "failed", "error": str(e), "agent": name}

    def _lazy_agent(self, name: str):
        mapping = {
            "task": "agents.task_agent.TaskAgent",
            "web_search": "agents.web_search_agent.WebSearchAgent",
            "growth": "agents.growth_agent.GrowthAgent",
            "shopify_ads": "agents.shopify_ads_agent.ShopifyAdsAgent",
            "scanner": "agents.scanner.ScannerAgent",
            "paradox": "agents.paradox.ParadoxAgent",
            "ghost_sentinel": "agents.ghost_sentinel_agent.GhostSentinelAgent",
            "knowledge": "agents.knowledge_agent.KnowledgeAgent",
            "mcp_tools": "agents.mcp_tool_agent.McpToolsAgent",
        }
        path = mapping.get(name)
        if not path:
            return None
        mod_name, cls_name = path.rsplit(".", 1)
        try:
            import importlib

            return getattr(importlib.import_module(mod_name), cls_name)()
        except Exception:
            return None

    def _collect_artifacts(self, out: Dict[str, Any], bb: Blackboard) -> None:
        for key in ("deliverables", "artifacts", "wrote"):
            val = out.get(key)
            if isinstance(val, list):
                for p in val:
                    bb.add_artifact(str(p))
            elif isinstance(val, str) and val:
                bb.add_artifact(val)
        # Nested result
        res = out.get("result")
        if isinstance(res, dict):
            self._collect_artifacts(res, bb)

    def _write_synthesis(
        self,
        goal: str,
        bb: Blackboard,
        tiles: List[TileSpec],
        force: bool = False,
    ) -> Optional[str]:
        try:
            MOSAIC_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            slug = re.sub(r"[^a-z0-9]+", "_", goal.lower())[:40].strip("_") or "run"
            path = MOSAIC_DIR / f"{slug}_{stamp}.md"

            lines = [
                f"# Mosaic synthesis — {stamp}",
                "",
                f"**Goal:** {goal}",
                f"**Assembly:** {bb.meta.get('assembly_id', '')}",
                f"**Tiles:** {', '.join(t.name if hasattr(t, 'name') else str(t) for t in tiles)}",
                "",
                "## Polymorphic roles used",
                "",
            ]
            for t in tiles:
                if hasattr(t, "name"):
                    lines.append(f"- **{t.name}** ({t.role}) — {t.specialty}")

            lines += ["", "## Observations", ""]
            for name, obs in bb.observations.items():
                if not isinstance(obs, dict):
                    lines.append(f"### {name}\n\n{obs}\n")
                    continue
                formatted = obs.get("formatted") or obs.get("message") or ""
                lines.append(f"### {name}")
                lines.append("")
                if formatted:
                    lines.append(str(formatted)[:2500])
                else:
                    lines.append(f"```json\n{json.dumps({k: obs[k] for k in list(obs)[:8] if k != 'formatted'}, default=str)[:1500]}\n```")
                lines.append("")

            if bb.artifacts:
                lines += ["## Artifacts", ""]
                for a in bb.artifacts:
                    lines.append(f"- {a}")
                lines.append("")

            if bb.errors:
                lines += ["## Errors (adapted around)", ""]
                for e in bb.errors:
                    lines.append(f"- {e}")
                lines.append("")

            lines += [
                "## Synthetic learning note",
                "",
                "This run is logged to `data/learning/mosaic_trajectories.jsonl` "
                "for future fine-tune / skill synthesis.",
                "",
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return str(path)
        except Exception:
            return None

    def _format(
        self,
        goal: str,
        tiles: List[TileSpec],
        steps: List[Dict[str, Any]],
        bb: Blackboard,
    ) -> str:
        lines = [
            "🧬 Mosaic executed (polymorphic auto-assembly)",
            "",
            f"Goal: {goal[:200]}",
            "",
            f"Tiles: {' → '.join(t.name for t in tiles)}",
            "",
            "Steps:",
        ]
        for s in steps:
            st = s.get("step")
            if st == "assemble":
                lines.append(f"  • assemble {[x['name'] for x in s.get('tiles', [])]}")
            elif st == "tile":
                lines.append(
                    f"  • {s.get('tile')} [{s.get('role')}] via {s.get('agent') or s.get('path') or '—'} → {s.get('status')}"
                )
            elif st == "adapt":
                lines.append(f"  • adapt {s.get('from')} → {s.get('to')} [{s.get('status')}]")
            else:
                lines.append(f"  • {s}")

        if bb.artifacts:
            lines.append("")
            lines.append("Artifacts:")
            for a in bb.artifacts:
                lines.append(f"  • {a}")

        # Surface best human-readable tile output
        for key in ("code", "research", "growth", "ads", "execute"):
            obs = bb.observations.get(key)
            if isinstance(obs, dict) and obs.get("formatted"):
                snippet = str(obs["formatted"])[:800]
                lines.append("")
                lines.append(f"--- {key} ---")
                lines.append(snippet)
                break

        lines.append("")
        lines.append(
            "Mosaic = auto tile assembly · polymorphic roles · agentic action · adaptive re-route · synthetic trajectories."
        )
        return "\n".join(lines)

    def _record_trajectory(self, result: MosaicResult) -> None:
        try:
            TRAJECTORY_EXTRA.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": time.time(),
                "assembly_id": result.assembly_id,
                "goal": result.goal[:500],
                "tiles": result.tiles,
                "status": result.status,
                "artifacts": result.artifacts,
                "steps": [
                    {k: s[k] for k in s if k in ("step", "tile", "agent", "status", "role")}
                    for s in result.steps
                ],
            }
            with open(TRAJECTORY_EXTRA, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass

        # Also feed main trajectory pipeline when available
        try:
            from learning.trajectory import record_task

            record_task(
                task_id=result.assembly_id,
                intent="mosaic",
                agent="mosaic",
                status="done" if result.status in ("ok", "degraded") else "failed",
                payload={"goal": result.goal, "tiles": result.tiles},
                result={"status": result.status, "artifacts": result.artifacts},
            )
        except Exception:
            pass


_mosaic: Optional[MosaicRuntime] = None


def get_mosaic() -> MosaicRuntime:
    global _mosaic
    if _mosaic is None:
        _mosaic = MosaicRuntime()
    return _mosaic
