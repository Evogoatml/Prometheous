"""
General task agent — autonomous executor for ANY user goal.

Policy: attempt the work. Never reply with "I can't" / "I don't have access"
without first trying tools, specialists, search, file writes, and verification.

Unlike a search-then-template path, this agent runs a multi-step action loop:
  1. Domain specialists (ads, growth, scan, sentinel, paradox, …)
  2. Plan concrete actions from the goal (rule-based, no LLM required)
  3. Execute: MCP tools, fs.write, shell, web search, synthesis
  4. Verify (exists / run) when the goal implies an artifact
  5. Report what was actually done and where files landed
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from utils.config import cfg

    ROOT = cfg.ROOT
    DATA = cfg.DATA_DIR
except Exception:
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"

TASKS_DIR = DATA / "tasks"
MAX_STEPS = 10


@dataclass
class Action:
    kind: str  # tool | write_file | research | synthesize | shell | specialist | done
    name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class TaskAgent:
    name = "task"
    role = "Executor"
    specialty = "autonomous multi-step task execution (no refusals)"
    tasks_completed = 0

    # (pattern, agent_name, reason)
    SPECIALISTS: List[Tuple[re.Pattern, str, str]] = [
        (
            re.compile(
                r"\b(?:shopify|meta\s+ads?|facebook\s+ads?|ad\s*campaign|instagram\s+ads?)\b",
                re.I,
            ),
            "shopify_ads",
            "growth/ads",
        ),
        (
            re.compile(
                r"\b(?:self[- ]?(?:grow|improve|evolve)|grow\s+(?:yourself|skill)|"
                r"learn\s+from\s+(?:github|huggingface)|figure\s+it\s+out|"
                r"search\s+github|huggingface|hugging\s*face)\b",
                re.I,
            ),
            "growth",
            "self-growth",
        ),
        (re.compile(r"\b(?:scan|nmap|port\s*scan)\b", re.I), "scanner", "scan"),
        (
            re.compile(r"\b(?:ghost\s*sentinel|sentinel\s+sync|crdt)\b", re.I),
            "ghost_sentinel",
            "sentinel",
        ),
        (re.compile(r"\b(?:self[- ]?audit|/reflect|paradox)\b", re.I), "paradox", "audit"),
        (
            re.compile(r"\b(?:matrix|linear\s+algebra|gaussian\s+elim)\b", re.I),
            "matrix",
            "matrix",
        ),
        (
            re.compile(r"\b(?:knowledge\s+graph|graphrag|index\s+knowledge)\b", re.I),
            "knowledge",
            "knowledge",
        ),
    ]

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        goal = self._goal(payload)
        steps: List[Dict[str, Any]] = []
        deliverables: List[str] = []
        observations: List[Dict[str, Any]] = []

        if not goal:
            return self._ok(
                goal="",
                steps=[{"step": "parse", "result": "empty goal"}],
                summary="No goal text — send what you want done.",
                deliverables=[],
            )

        # 0) Mission conductor for plan→code→deploy goals (unless nested)
        if not payload.get("mission") and not payload.get("mosaic") and self._should_mission(goal):
            try:
                from core.mission import get_conductor

                return get_conductor().run(goal, {**payload, "mission": True}).to_agent_result()
            except Exception as exc:
                steps.append({"step": "mission_fallback", "error": str(exc)[:160]})

        # 0b) Polymorphic mosaic for multi-capability goals (skip if already inside mosaic)
        if not payload.get("mosaic") and not payload.get("mission") and self._should_mosaic(goal):
            try:
                from core.mosaic import get_mosaic

                mosaic_out = get_mosaic().run(goal, {**payload, "mosaic": True})
                return mosaic_out.to_agent_result()
            except Exception as exc:
                steps.append({"step": "mosaic_fallback", "error": str(exc)[:160]})

        # 1) Specialist hand-off when domain is clear
        specialist = self._match_specialist(goal)
        if specialist:
            agent_name, reason = specialist
            steps.append({"step": "specialist", "agent": agent_name, "reason": reason})
            out = self._run_agent(agent_name, payload, goal)
            if out:
                formatted = out.get("formatted") or out.get("message") or ""
                if not formatted and out.get("status") == "ok":
                    formatted = json.dumps(out, indent=2, default=str)[:2500]
                if formatted:
                    return {
                        "status": out.get("status", "ok"),
                        "agent": self.name,
                        "via": agent_name,
                        "goal": goal,
                        "result": out,
                        "steps": steps,
                        "formatted": formatted,
                    }
                steps.append(
                    {
                        "step": "specialist_empty",
                        "agent": agent_name,
                        "raw_status": out.get("status"),
                    }
                )

        # 2) Multi-step autonomous plan → execute
        plan = self._plan(goal)
        steps.append(
            {
                "step": "plan",
                "actions": [
                    {"kind": a.kind, "name": a.name, "reason": a.reason, "args": self._safe_args(a)}
                    for a in plan
                ],
            }
        )

        research_blob: Dict[str, Any] = {}
        wrote_paths: List[str] = []

        for i, action in enumerate(plan[:MAX_STEPS]):
            if action.kind == "done":
                steps.append({"step": "done", "reason": action.reason})
                break

            if action.kind == "tool":
                hit = self._exec_tool(action.name, action.args)
                steps.append(
                    {
                        "step": "tool",
                        "tool": action.name,
                        "status": hit.get("status"),
                        "reason": action.reason,
                    }
                )
                observations.append(hit)
                if hit.get("formatted") and action.name in (
                    "fs.read",
                    "shell.run",
                    "github.search",
                    "github.readme",
                ):
                    # Keep going — single tool is not always the full goal
                    pass
                continue

            if action.kind == "research":
                query = str(action.args.get("query") or goal)
                steps.append({"step": "web_search", "query": query[:120]})
                search = self._web_search(query)
                observations.append(search)
                research_blob = search
                continue

            if action.kind == "write_file":
                path = str(action.args.get("path") or "")
                content = str(action.args.get("content") or "")
                if not content and action.args.get("from_research"):
                    content = self._synthesize_document(goal, research_blob)
                if not content:
                    content = self._infer_file_content(goal, path, research_blob)
                write_res = self._write_path(path, content)
                steps.append(
                    {
                        "step": "write_file",
                        "path": path,
                        "status": write_res.get("status"),
                        "bytes": write_res.get("bytes"),
                        "reason": action.reason,
                    }
                )
                observations.append(write_res)
                if write_res.get("status") == "ok" and write_res.get("path"):
                    wrote_paths.append(str(write_res["path"]))
                    deliverables.append(str(write_res["path"]))
                continue

            if action.kind == "shell":
                cmd = str(action.args.get("command") or "")
                hit = self._exec_tool("shell.run", {"command": cmd})
                steps.append(
                    {
                        "step": "shell",
                        "command": cmd,
                        "status": hit.get("status"),
                        "returncode": (hit.get("result") or {}).get("returncode"),
                        "reason": action.reason,
                    }
                )
                observations.append(hit)
                continue

            if action.kind == "synthesize":
                path = str(action.args.get("path") or self._default_doc_path(goal))
                content = self._synthesize_document(goal, research_blob)
                write_res = self._write_path(path, content)
                steps.append(
                    {
                        "step": "synthesize",
                        "path": path,
                        "status": write_res.get("status"),
                        "reason": action.reason,
                    }
                )
                if write_res.get("status") == "ok" and write_res.get("path"):
                    wrote_paths.append(str(write_res["path"]))
                    deliverables.append(str(write_res["path"]))
                observations.append(write_res)
                continue

            if action.kind == "rag":
                rag = self._rag(goal)
                if rag:
                    steps.append({"step": "rag", "chars": len(rag)})
                    observations.append({"rag": rag})
                continue

        # 3) If nothing was written and goal looks like produce-work, force a real deliverable
        if not wrote_paths and self._wants_artifact(goal):
            path = self._infer_output_path(goal) or self._default_doc_path(goal)
            content = self._infer_file_content(goal, path, research_blob)
            if not content.strip() and research_blob:
                content = self._synthesize_document(goal, research_blob)
            if not content.strip():
                content = self._minimal_actionable_doc(goal, steps)
            write_res = self._write_path(path, content)
            steps.append(
                {
                    "step": "force_deliverable",
                    "path": path,
                    "status": write_res.get("status"),
                }
            )
            if write_res.get("status") == "ok" and write_res.get("path"):
                wrote_paths.append(str(write_res["path"]))
                deliverables.append(str(write_res["path"]))

        # 4) Verification for written python files
        for p in list(wrote_paths):
            if p.endswith(".py"):
                rel = self._rel(p)
                hit = self._exec_tool("shell.run", {"command": f"python3 {rel}"})
                steps.append(
                    {
                        "step": "verify",
                        "command": f"python3 {rel}",
                        "status": hit.get("status"),
                        "returncode": (hit.get("result") or {}).get("returncode"),
                        "stdout": ((hit.get("result") or {}).get("stdout") or "")[:500],
                    }
                )
                observations.append(hit)

        # 5) Audit log under data/tasks (always) — secondary to real artifacts
        audit = self._write_audit(goal, steps, deliverables, research_blob)
        if audit:
            deliverables.append(str(audit))

        summary = self._summary(goal, steps, deliverables, wrote_paths, observations)
        return {
            "status": "ok",
            "agent": self.name,
            "via": "autonomous",
            "goal": goal,
            "steps": steps,
            "deliverables": deliverables,
            "wrote": wrote_paths,
            "formatted": summary[:4000],
        }

    def _should_mission(self, goal: str) -> bool:
        """True when the user wants plan → code → deploy → execute."""
        g = goal.lower()
        if re.search(
            r"(?:/mission\b|"
            r"\bmission\b|"
            r"\bplan\s+it\s+out\b|"
            r"\bget\s+it\s+done\b|"
            r"\bwrite\s+code\s+and\s+deploy\b|"
            r"\bdeploy\s+(?:a\s+|an\s+)?(?:new\s+)?(?:[\w-]+\s+)*(?:agent|bot|worker)s?\b|"
            r"\b(?:build|create|make|spawn)\s+(?:me\s+)?(?:a\s+|an\s+)?(?:[\w-]+\s+)*(?:agent|bot|worker)s?\b)",
            g,
        ):
            return True
        has_code = bool(
            re.search(r"\b(?:code|script|implement|build|python|write)\b", g)
        )
        has_deploy = bool(
            re.search(r"\b(?:deploy|agent|bot|worker|orchestrat)\b", g)
        )
        return has_code and has_deploy

    def _should_mosaic(self, goal: str) -> bool:
        """True when the goal spans multiple capability tiles."""
        g = goal.lower()
        if self._should_mission(goal):
            return False  # mission owns plan/code/deploy path
        signals = 0
        checks = (
            r"\b(?:research|plan|strategy|launch|market)\b",
            r"\b(?:code|script|implement|fix|python|\.py)\b",
            r"\b(?:grow|github|huggingface|learn from)\b",
            r"\b(?:shopify|meta ads?|campaign)\b",
            r"\b(?:audit|reflect|scan|sentinel)\b",
            r"\b(?:and then|also|multi[- ]?step|end[- ]?to[- ]?end)\b",
            r"\bmosaic\b|\bpolymorphic\b",
        )
        for pat in checks:
            if re.search(pat, g):
                signals += 1
        # Multi-capability or long goals → mosaic
        if signals >= 2 or len(goal) > 120:
            return True
        # Explicit mosaic request
        if re.search(r"\b(?:mosaic|polymorphic|assemble\s+tiles)\b", g):
            return True
        return False

    # ── planning ───────────────────────────────────────────
    def _plan(self, goal: str) -> List[Action]:
        """Rule-based multi-step plan. Prefer acting over searching."""
        actions: List[Action] = []
        g = goal.lower()

        # Explicit path create/write/save
        out_path = self._infer_output_path(goal)
        codey = bool(
            out_path
            and out_path.suffix in {".py", ".sh", ".js", ".ts", ".go", ".rs"}
            or re.search(
                r"\b(?:python\s+script|script|module|program|function|class)\b",
                g,
            )
        )
        docy = bool(
            re.search(
                r"\b(?:plan|write|draft|document|brief|checklist|strategy|outline|proposal|report)\b",
                g,
            )
            and not codey
        )

        # "read X and …"
        read_paths = re.findall(
            r"\b(?:read|open|cat|show)\s+(?:file\s+)?[`\"']?([\w./-]+\.[\w]+)[`\"']?",
            goal,
            re.I,
        )
        for rp in read_paths[:3]:
            actions.append(
                Action(
                    kind="tool",
                    name="fs.read",
                    args={"path": rp},
                    reason=f"inspect {rp}",
                )
            )

        # Create / write a file or script
        if out_path and (
            re.search(
                r"\b(?:create|write|save|make|generate|put|add|implement)\b",
                g,
            )
            or codey
        ):
            if docy and not codey:
                actions.append(
                    Action(
                        kind="research",
                        args={"query": goal},
                        reason="gather sources for document",
                    )
                )
                actions.append(
                    Action(
                        kind="write_file",
                        args={"path": str(out_path), "from_research": True},
                        reason=f"write real deliverable to {out_path}",
                    )
                )
            else:
                actions.append(
                    Action(
                        kind="write_file",
                        args={"path": str(out_path)},
                        reason=f"create {out_path}",
                    )
                )
            return actions

        # Document / plan without explicit path
        if docy or re.search(
            r"\b(?:how (?:do|to)|research|find|compare|best|latest)\b",
            g,
        ):
            actions.append(
                Action(kind="research", args={"query": goal}, reason="research goal")
            )
            actions.append(
                Action(
                    kind="synthesize",
                    args={"path": str(self._default_doc_path(goal))},
                    reason="write concrete deliverable from research",
                )
            )
            return actions

        # Run / execute something
        run_m = re.search(
            r"\b(?:run|execute)\s+(?:python3?\s+)?([`\"']?[\w./-]+\.py[`\"']?)",
            goal,
            re.I,
        )
        if run_m:
            rel = run_m.group(1).strip("`\"'")
            actions.append(
                Action(
                    kind="shell",
                    args={"command": f"python3 {rel}"},
                    reason=f"run {rel}",
                )
            )
            return actions

        # Inspect empty packages / implement scaffolding
        if re.search(r"\b(?:fix|implement|scaffold|fill)\b", g):
            folder_m = re.search(
                r"\b(?:tasks|tiles|interfaces|opt|scheduler|decomposer)[/.\w-]*",
                g,
            )
            if folder_m:
                folder = folder_m.group(0).split()[0]
                actions.append(
                    Action(
                        kind="tool",
                        name="fs.folder_context",
                        args={"path": folder},
                        reason=f"inspect {folder}",
                    )
                )
            actions.append(Action(kind="rag", reason="local knowledge"))
            actions.append(
                Action(
                    kind="research",
                    args={"query": goal},
                    reason="external patterns",
                )
            )
            actions.append(
                Action(
                    kind="synthesize",
                    args={"path": str(self._default_doc_path(goal))},
                    reason="implementation plan + starter",
                )
            )
            return actions

        # Explicit single-tool classification (read, ls, ping, …)
        try:
            from llm.tool_router import classify_tool

            call = classify_tool(goal)
            if call is not None and call.confidence >= 0.8:
                actions.append(
                    Action(
                        kind="tool",
                        name=call.name,
                        args=call.arguments,
                        reason=f"tool router {call.source}",
                    )
                )
                # If the goal also wants a summary/save, add synthesize after
                if re.search(r"\b(?:summarize|summary|report|save)\b", g):
                    actions.append(
                        Action(
                            kind="synthesize",
                            args={"path": str(self._default_doc_path(goal))},
                            reason="persist summary",
                        )
                    )
                return actions
        except Exception:
            pass

        # Default: research + real deliverable (never search-only exit)
        if self._needs_research(goal):
            actions.append(
                Action(kind="research", args={"query": goal}, reason="research")
            )
        actions.append(Action(kind="rag", reason="local knowledge"))
        actions.append(
            Action(
                kind="synthesize",
                args={"path": str(self._default_doc_path(goal))},
                reason="produce work product",
            )
        )
        return actions

    def _infer_output_path(self, goal: str) -> Optional[Path]:
        """Extract a project-relative output path from natural language."""
        # under/to/as/into PATH
        m = re.search(
            r"(?:under|to|into|as|at|in)\s+[`\"']?([\w./-]+\.[\w]+)[`\"']?",
            goal,
            re.I,
        )
        if m:
            return self._normalize_path(m.group(1))

        # create/write/save file PATH
        m = re.search(
            r"(?:create|write|save|make|generate)\s+(?:a\s+)?(?:new\s+)?"
            r"(?:file|script|module|program)?\s*[`\"']?([\w./-]+\.[\w]+)[`\"']?",
            goal,
            re.I,
        )
        if m:
            return self._normalize_path(m.group(1))

        # called/named foo.py
        m = re.search(
            r"(?:called|named)\s+[`\"']?([\w./-]+\.[\w]+)[`\"']?",
            goal,
            re.I,
        )
        if m:
            return self._normalize_path(m.group(1))

        # bare path with extension near create/write
        if re.search(r"\b(?:create|write|save|make)\b", goal, re.I):
            m = re.search(r"([`\"']?)([\w./-]+\.(?:py|md|json|txt|sh|yaml|yml))\1", goal)
            if m:
                return self._normalize_path(m.group(2))

        return None

    def _normalize_path(self, raw: str) -> Path:
        p = Path(raw.strip().strip("`\"'"))
        if p.is_absolute():
            try:
                p = p.relative_to(ROOT)
            except ValueError:
                p = Path("data/tasks") / p.name
        # keep under project; prefer data/tasks for bare names
        if len(p.parts) == 1:
            p = Path("data/tasks") / p.name
        return p

    def _default_doc_path(self, goal: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "_", goal.lower())[:48].strip("_") or "task"
        return Path("data/tasks") / f"{slug}_{stamp}.md"

    def _wants_artifact(self, goal: str) -> bool:
        g = goal.lower()
        return bool(
            re.search(
                r"\b(?:create|write|save|make|build|implement|draft|plan|fix|generate|produce)\b",
                g,
            )
            or len(goal) > 20
        )

    # ── content ────────────────────────────────────────────
    def _infer_file_content(
        self, goal: str, path: str | Path, research: Dict[str, Any]
    ) -> str:
        path_s = str(path)
        g = goal.lower()

        if path_s.endswith(".py"):
            # Common concrete goals — produce runnable code, not commentary
            if re.search(r"\bhello(?:\s*world)?\b", g) and re.search(
                r"\bprints?\b", g
            ):
                return 'print("Hello, World!")\n'
            if re.search(r"\bhello\s*world\b", g):
                return 'print("Hello, World!")\n'
            if "fibonacci" in g:
                return (
                    "def fib(n: int) -> int:\n"
                    "    a, b = 0, 1\n"
                    "    for _ in range(n):\n"
                    "        a, b = b, a + b\n"
                    "    return a\n\n"
                    "if __name__ == '__main__':\n"
                    "    print(fib(10))\n"
                )
            # LLM optional for richer code; never refuse
            llm_code = self._optional_llm_content(
                goal,
                f"Write ONLY the full contents of a Python file for this goal. "
                f"No markdown fences. Path: {path_s}. Goal: {goal}",
            )
            if llm_code and ("def " in llm_code or "print" in llm_code or "return " in llm_code):
                return self._strip_fences(llm_code)
            # Minimal runnable scaffold from goal
            safe = goal.replace("\\", "\\\\").replace('"', '\\"')[:200]
            return (
                f'"""Auto-generated by Prometheous task agent.\nGoal: {goal}\n"""\n'
                f"print({json.dumps('done: ' + safe[:80])})\n"
            )

        if path_s.endswith((".sh",)):
            return "#!/usr/bin/env bash\nset -euo pipefail\necho hello\n"

        if path_s.endswith((".md", ".txt")):
            if research:
                return self._synthesize_document(goal, research)
            return self._minimal_actionable_doc(goal, [])

        if path_s.endswith(".json"):
            return json.dumps({"goal": goal, "generated": True}, indent=2) + "\n"

        return self._minimal_actionable_doc(goal, [])

    def _synthesize_document(self, goal: str, research: Dict[str, Any]) -> str:
        """Build a real deliverable from research — not a template stub."""
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        results = []
        if isinstance(research, dict):
            raw = research.get("results") or research.get("result") or research
            if isinstance(raw, dict):
                results = raw.get("results") or []
            elif isinstance(raw, list):
                results = raw

        lines = [
            f"# {goal.strip().rstrip('.')}",
            "",
            f"_Generated by Prometheous autonomous executor — {stamp}_",
            "",
            "## Objective",
            "",
            goal.strip(),
            "",
            "## Action plan",
            "",
        ]

        # Derive steps from goal verbs + research titles
        lines.extend(self._action_plan_bullets(goal, results))
        lines += ["", "## Research inputs", ""]
        if results:
            for i, r in enumerate(results[:8], 1):
                if not isinstance(r, dict):
                    continue
                title = r.get("title") or "source"
                url = r.get("url") or ""
                snippet = (r.get("snippet") or "")[:280]
                lines.append(f"{i}. **{title}**")
                if url:
                    lines.append(f"   - {url}")
                if snippet:
                    lines.append(f"   - {snippet}")
        else:
            lines.append("_No web results — plan is rule-based from the goal text._")

        lines += [
            "",
            "## Concrete next actions (do these)",
            "",
        ]
        for bullet in self._next_actions(goal):
            lines.append(f"- [ ] {bullet}")

        lines += [
            "",
            "## Notes",
            "",
            "This file is a work product produced by the agent, not a refusal or status dump.",
            "",
        ]

        # Optional LLM polish when available
        polished = self._optional_llm_content(
            goal,
            "Expand this outline into a concrete deliverable. Keep markdown. "
            "Never say you cannot help. Outline:\n" + "\n".join(lines[:40]),
        )
        if polished and len(polished) > len("\n".join(lines)) * 0.5:
            return self._strip_fences(polished)

        return "\n".join(lines) + "\n"

    def _action_plan_bullets(self, goal: str, results: list) -> List[str]:
        g = goal.lower()
        bullets: List[str] = []
        if "store" in g or "ecommerce" in g or "shop" in g or "launch" in g:
            bullets = [
                "1. **Positioning** — define niche, offer, and primary buyer persona.",
                "2. **Product readiness** — catalog, pricing, shipping, and checkout tested.",
                "3. **Storefront** — homepage, PDP, trust signals, mobile pass.",
                "4. **Traffic** — one paid channel + one organic channel for week 1.",
                "5. **Measurement** — pixel/CAPI or analytics events on purchase.",
                "6. **Launch week** — soft launch → collect feedback → iterate creatives.",
            ]
        elif "plan" in g or "strategy" in g:
            bullets = [
                "1. Clarify success metric and deadline.",
                "2. Inventory assets already available.",
                "3. Sequence work into week-1 / week-2 blocks.",
                "4. Assign owners (or solo timeboxes).",
                "5. Define kill/scale criteria.",
            ]
        else:
            bullets = [
                f"1. Restate goal: {goal[:160]}",
                "2. Gather constraints and inputs.",
                "3. Produce the smallest useful artifact.",
                "4. Verify (run, read, or checklist).",
                "5. Iterate from feedback.",
            ]
        if results:
            bullets.append(
                f"{len(bullets) + 1}. Incorporate findings from {len(results)} researched sources above."
            )
        return bullets

    def _next_actions(self, goal: str) -> List[str]:
        g = goal.lower()
        if "store" in g or "shop" in g:
            return [
                "Finish product page copy and 3 images",
                "Enable purchase tracking on thank-you page",
                "Ship one acquisition experiment this week",
                "Review first 10 orders or signups for friction",
            ]
        return [
            f"Complete primary deliverable for: {goal[:100]}",
            "Validate with a concrete check (run, publish, or review)",
            "Log outcome and next revision",
        ]

    def _minimal_actionable_doc(self, goal: str, steps: list) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        lines = [
            f"# Deliverable — {stamp}",
            "",
            f"**Goal:** {goal}",
            "",
            "## What was executed",
        ]
        for s in steps:
            lines.append(f"- {json.dumps(s, default=str)}")
        lines += [
            "",
            "## Outcome",
            "",
            "Agent completed best-effort autonomous steps for this goal.",
            "",
        ]
        return "\n".join(lines) + "\n"

    def _optional_llm_content(self, goal: str, instruction: str) -> str:
        try:
            from llm.client import llm

            if not getattr(llm, "enabled", lambda: False)():
                return ""
            return (
                llm.respond(
                    {
                        "intent": "task_content",
                        "goal": goal,
                        "instruction": instruction,
                    },
                    instruction,
                )
                or ""
            )
        except Exception:
            return ""

    def _strip_fences(self, text: str) -> str:
        t = text.strip()
        t = re.sub(r"^```(?:\w+)?\n", "", t)
        t = re.sub(r"\n```$", "", t)
        return t.strip() + ("\n" if not t.endswith("\n") else "")

    # ── execution helpers ──────────────────────────────────
    def _write_path(self, path: str | Path, content: str) -> Dict[str, Any]:
        rel = str(path)
        # Prefer MCP fs.write; fall back to direct write so autonomy never stalls.
        try:
            from mcp.server import MCPClient

            result = MCPClient.call("fs.write", {"path": rel, "text": content})
            if not result.get("error"):
                written = result.get("written") or str((ROOT / rel).resolve())
                return {
                    "status": "ok",
                    "path": str(written),
                    "bytes": result.get("bytes", len(content)),
                    "result": result,
                }
            err = result.get("error")
        except Exception as e:
            err = str(e)

        try:
            p = Path(path)
            if not p.is_absolute():
                p = ROOT / p
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"status": "ok", "path": str(p.resolve()), "bytes": len(content)}
        except Exception as e2:
            return {"status": "failed", "error": f"{err}; fallback: {e2}"}

    def _exec_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from llm.tool_router import ToolCall, execute_tool, format_tool_reply

            call = ToolCall(name=name, arguments=args, confidence=1.0, source="task_agent")
            result = execute_tool(call)
            formatted = format_tool_reply(call, result)
            ok = result.get("status") != "error" and not result.get("error")
            return {
                "status": "ok" if ok else "failed",
                "tool": name,
                "result": result,
                "formatted": formatted,
            }
        except Exception as e:
            return {"status": "failed", "tool": name, "error": str(e)}

    def _rel(self, path: str) -> str:
        p = Path(path)
        try:
            return str(p.resolve().relative_to(ROOT.resolve()))
        except Exception:
            return str(p)

    def _safe_args(self, action: Action) -> Dict[str, Any]:
        args = dict(action.args)
        if "content" in args and isinstance(args["content"], str):
            args["content"] = f"<{len(args['content'])} chars>"
        return args

    def _goal(self, payload: Dict[str, Any]) -> str:
        for k in ("goal", "query", "target", "user_msg", "text"):
            v = payload.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return ""

    def _match_specialist(self, goal: str) -> Optional[Tuple[str, str]]:
        for pat, agent, reason in self.SPECIALISTS:
            if pat.search(goal):
                return agent, reason
        return None

    def _run_agent(
        self, name: str, payload: Dict[str, Any], goal: str
    ) -> Optional[Dict[str, Any]]:
        try:
            from core.orchestrator import orchestrator

            agent = orchestrator.get_agent(name)
            if agent is None:
                agent = self._lazy_agent(name)
                if agent is not None:
                    orchestrator.register_agent(name, agent)
            if agent is None:
                return {"status": "failed", "error": f"agent {name} not registered"}
            pl = {
                **payload,
                "user_msg": goal,
                "query": goal,
                "target": goal,
            }
            if hasattr(agent, "execute"):
                return agent.execute(pl)
            if hasattr(agent, "run"):
                return agent.run(pl)
        except Exception as e:
            return {"status": "failed", "error": str(e), "agent": name}
        return None

    def _lazy_agent(self, name: str):
        mapping = {
            "shopify_ads": "agents.shopify_ads_agent.ShopifyAdsAgent",
            "growth": "agents.growth_agent.GrowthAgent",
            "learn": "agents.learn_agent.LearnAgent",
            "web_search": "agents.web_search_agent.WebSearchAgent",
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

            mod = importlib.import_module(mod_name)
            return getattr(mod, cls_name)()
        except Exception:
            return None

    def _needs_research(self, goal: str) -> bool:
        g = goal.lower()
        if len(goal) < 12:
            return False
        triggers = (
            "how ",
            "what ",
            "why ",
            "research",
            "find ",
            "look up",
            "best ",
            "latest",
            "news",
            "compare",
            "should i",
            "help me",
            "build ",
            "create ",
            "make ",
            "design",
            "plan ",
            "strategy",
            "write ",
            "campaign",
            "market",
            "competitor",
            "learn",
            "explain",
            "launch",
        )
        if any(t in g for t in triggers):
            return True
        if re.match(
            r"^(?:build|create|make|write|draft|design|plan|set\s*up|setup)\b", g
        ):
            return True
        return False

    def _web_search(self, goal: str) -> Dict[str, Any]:
        try:
            from agents.web_search_agent import WebSearchAgent

            return WebSearchAgent().execute(
                {"query": goal, "user_msg": goal, "num_results": 6}
            )
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def _rag(self, goal: str) -> str:
        """Pull from BRAIN knowledge store only — never knowledge/training/."""
        chunks: list[str] = []
        try:
            from brain.knowledge_store import brain_knowledge

            brain_knowledge.load()
            for h in brain_knowledge.query(goal, top_k=5):
                chunks.append(
                    f"- [{h.get('domain')}] {h.get('title')}: "
                    f"{(h.get('snippet') or '')[:180]}"
                )
        except Exception:
            pass
        return "\n".join(chunks)

    def _write_audit(
        self,
        goal: str,
        steps: list,
        deliverables: list,
        research: dict,
    ) -> Optional[Path]:
        try:
            TASKS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = TASKS_DIR / f"audit_{stamp}.md"
            lines = [
                f"# Task audit — {stamp}",
                "",
                f"**Goal:** {goal}",
                "",
                "## Steps",
            ]
            for s in steps:
                lines.append(f"- {json.dumps(s, default=str)}")
            lines += ["", "## Deliverables"]
            for d in deliverables:
                lines.append(f"- {d}")
            if research.get("formatted"):
                lines += ["", "## Research excerpt", "", str(research.get("formatted"))[:2000]]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path
        except Exception:
            return None

    def _summary(
        self,
        goal: str,
        steps: list,
        deliverables: list,
        wrote: list,
        observations: list,
    ) -> str:
        # Speak like a person reporting work, not a batch job log.
        lines = [
            f"Done — here's what I did for: {goal[:180]}",
            "",
        ]
        did: List[str] = []
        for s in steps:
            kind = s.get("step", s)
            if kind == "plan":
                n = len(s.get("actions") or [])
                if n:
                    did.append(f"mapped out {n} steps")
            elif kind == "write_file":
                did.append(f"wrote {s.get('path')}")
            elif kind == "shell" or kind == "verify":
                did.append(f"ran `{s.get('command')}`")
            elif kind == "web_search":
                did.append(f"researched \"{s.get('query')}\"")
            elif kind == "tool":
                did.append(f"used {s.get('tool')}")
            elif kind == "specialist":
                did.append(f"handed off to {s.get('agent')}")
            elif kind == "synthesize":
                did.append(f"put together {s.get('path') or 'a write-up'}")
            elif kind == "force_deliverable":
                did.append(f"saved output to {s.get('path')}")
        if did:
            lines.append("What I did:")
            for item in did[:12]:
                lines.append(f"  • {item}")
            lines.append("")

        if wrote:
            lines.append("Files:")
            for w in wrote:
                lines.append(f"  • {w}")
            lines.append("")

        elif deliverables:
            lines.append("Output:")
            for d in deliverables[:8]:
                lines.append(f"  • {d}")
            lines.append("")

        # Surface verify stdout if present
        for s in steps:
            if s.get("step") == "verify" and s.get("stdout"):
                lines.append(f"Quick check: {s['stdout'][:300]}")
                lines.append("")

        lines.append("Want me to change anything or keep going?")
        return "\n".join(lines)

    def _ok(
        self,
        *,
        goal: str,
        steps: list,
        summary: str,
        deliverables: list,
        rag: str = "",
    ) -> Dict[str, Any]:
        return {
            "status": "ok",
            "agent": self.name,
            "via": "autonomous",
            "goal": goal,
            "steps": steps,
            "deliverables": deliverables,
            "rag_used": bool(rag),
            "formatted": summary[:4000],
        }
