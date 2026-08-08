"""
Self-growth agent — use GitHub + HuggingFace to figure things out and extend Prometheous.

Pipeline:
  1. Interpret growth goal
  2. Search GitHub repos + HF models/datasets
  3. Pull useful README/snippets/dataset samples into data/external/
  4. Synthesize a skill module under data/learning/skills/ (always)
  5. Optionally install into agents/ when PROM_SELF_GROW_INSTALL=1
  6. Append trajectory for finetune pipeline
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.config import cfg

    ROOT = cfg.ROOT
    DATA = cfg.DATA_DIR
except Exception:
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"

SKILLS_DIR = DATA / "learning" / "skills"
GROWTH_DIR = DATA / "learning" / "growth"


class GrowthAgent:
    name = "growth"
    role = "SelfGrowth"
    specialty = "GitHub + HuggingFace research → skills → optional self-install"
    tasks_completed = 0

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        goal = str(
            payload.get("goal")
            or payload.get("query")
            or payload.get("user_msg")
            or payload.get("target")
            or ""
        ).strip()
        if not goal:
            return {
                "status": "failed",
                "agent": self.name,
                "formatted": "Usage: grow <capability>  e.g. grow agent memory from github",
            }

        steps: List[dict] = []
        artifacts: List[str] = []

        # ── GitHub (broaden query until hits) ──
        gh_queries = self._gh_queries(goal)
        gh: Dict[str, Any] = {"results": [], "readmes": []}
        try:
            from tools.github_api import search_repositories, get_readme, format_search_for_chat

            seen = set()
            for gh_query in gh_queries:
                batch = search_repositories(gh_query, limit=5)
                steps.append(
                    {"step": "github_search", "query": gh_query, "hits": len(batch.get("results") or [])}
                )
                for r in batch.get("results") or []:
                    fn = r.get("full_name")
                    if fn and fn not in seen:
                        seen.add(fn)
                        gh["results"].append(r)
                if len(gh["results"]) >= 5:
                    break
            gh["status"] = "ok"
            gh["query"] = " | ".join(gh_queries)
            gh["total_count"] = len(gh["results"])
            readmes: List[str] = []
            for repo in gh["results"][:3]:
                full = repo.get("full_name") or ""
                if "/" not in full:
                    continue
                owner, name = full.split("/", 1)
                try:
                    rm = get_readme(owner, name)
                    if rm.get("status") == "ok" and rm.get("content"):
                        readmes.append(f"# {full}\n\n{rm['content'][:4000]}")
                        steps.append({"step": "github_readme", "repo": full})
                except Exception as e:
                    steps.append({"step": "github_readme_fail", "repo": full, "error": str(e)[:120]})
            gh["readmes"] = readmes
            gh["formatted"] = format_search_for_chat(gh)
        except Exception as e:
            steps.append({"step": "github_error", "error": str(e)[:200]})
            gh = {"status": "error", "error": str(e), "results": [], "readmes": []}

        # ── HuggingFace (broaden until hits) ──
        hf_queries = self._hf_queries(goal)
        hf_models: Dict[str, Any] = {"results": []}
        hf_datasets: Dict[str, Any] = {"results": []}
        try:
            from tools.huggingface_api import (
                search_models,
                search_datasets,
                pull_dataset_rows,
                format_search_for_chat,
            )

            seen_m, seen_d = set(), set()
            for hf_q in hf_queries:
                mbatch = search_models(hf_q, limit=5)
                dbatch = search_datasets(hf_q, limit=5)
                steps.append(
                    {
                        "step": "hf_search",
                        "query": hf_q,
                        "models": len(mbatch.get("results") or []),
                        "datasets": len(dbatch.get("results") or []),
                    }
                )
                for r in mbatch.get("results") or []:
                    i = r.get("id")
                    if i and i not in seen_m:
                        seen_m.add(i)
                        hf_models["results"].append(r)
                for r in dbatch.get("results") or []:
                    i = r.get("id")
                    if i and i not in seen_d:
                        seen_d.add(i)
                        hf_datasets["results"].append(r)
                if len(hf_models["results"]) >= 5 and len(hf_datasets["results"]) >= 3:
                    break
            hf_models["status"] = "ok"
            hf_models["kind"] = "models"
            hf_models["query"] = " | ".join(hf_queries)
            hf_datasets["status"] = "ok"
            hf_datasets["kind"] = "datasets"
            hf_datasets["query"] = " | ".join(hf_queries)
            top_ds = (hf_datasets.get("results") or [{}])[0].get("id")
            if top_ds and payload.get("pull_data", True):
                pull = pull_dataset_rows(top_ds, max_rows=int(payload.get("max_rows") or 30))
                steps.append(
                    {"step": "hf_pull", "dataset": top_ds, "result": pull.get("status"), "path": pull.get("path")}
                )
                if pull.get("path"):
                    artifacts.append(str(pull["path"]))
                if pull.get("info_path"):
                    artifacts.append(str(pull["info_path"]))
                hf_datasets["pull"] = pull
            hf_models["formatted"] = format_search_for_chat(hf_models)
            hf_datasets["formatted"] = format_search_for_chat(hf_datasets)
        except Exception as e:
            steps.append({"step": "hf_error", "error": str(e)[:200]})

        # ── Synthesize skill ──
        skill_name = self._skill_name(goal)
        skill_body = self._synthesize_skill(goal, skill_name, gh, hf_models, hf_datasets)
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        skill_path = SKILLS_DIR / f"{skill_name}.py"
        skill_path.write_text(skill_body, encoding="utf-8")
        artifacts.append(str(skill_path))
        steps.append({"step": "skill_written", "path": str(skill_path)})

        # Manifest
        GROWTH_DIR.mkdir(parents=True, exist_ok=True)
        manifest = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "goal": goal,
            "skill_name": skill_name,
            "skill_path": str(skill_path),
            "github": {"query": gh_query, "repos": [r.get("full_name") for r in (gh.get("results") or [])]},
            "hf_models": [r.get("id") for r in (hf_models.get("results") or [])],
            "hf_datasets": [r.get("id") for r in (hf_datasets.get("results") or [])],
            "steps": steps,
            "artifacts": artifacts,
        }
        man_path = GROWTH_DIR / f"growth_{int(time.time())}.json"
        man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        artifacts.append(str(man_path))

        # Trajectory for finetune
        try:
            traj = DATA / "learning" / "trajectories.jsonl"
            traj.parent.mkdir(parents=True, exist_ok=True)
            with open(traj, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "success": True,
                            "intent": "growth",
                            "agent": self.name,
                            "payload": {"goal": goal},
                            "result": {"skill": skill_name, "artifacts": artifacts},
                            "duration": 0,
                            "task_id": f"grow-{int(time.time())}",
                        }
                    )
                    + "\n"
                )
            steps.append({"step": "trajectory_logged"})
        except Exception:
            pass

        # Optional install into agents/
        installed = None
        import os

        if os.getenv("PROM_SELF_GROW_INSTALL", "").lower() in ("1", "true", "yes"):
            installed = self._install_skill(skill_name, skill_body)
            steps.append({"step": "install", "result": installed})

        formatted = self._format(goal, skill_name, skill_path, gh, hf_models, hf_datasets, artifacts, installed, steps)
        return {
            "status": "ok",
            "agent": self.name,
            "goal": goal,
            "skill_name": skill_name,
            "skill_path": str(skill_path),
            "artifacts": artifacts,
            "installed": installed,
            "steps": steps,
            "formatted": formatted,
        }

    def _keywords(self, goal: str) -> List[str]:
        stop = {
            "grow", "learn", "from", "the", "a", "an", "and", "or", "to", "for", "my", "me",
            "self", "improve", "yourself", "prometheous", "agent", "using", "with", "via",
            "github", "huggingface", "hf", "please", "build", "create", "make", "how",
        }
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", goal.lower())
        return [w for w in words if w not in stop]

    def _gh_queries(self, goal: str) -> List[str]:
        kws = self._keywords(goal)
        queries = []
        if kws:
            queries.append(" ".join(kws[:4]) + " language:python")
            queries.append(kws[0] + " language:python stars:>50")
        # domain fallbacks from goal text
        fallbacks = []
        g = goal.lower()
        if any(x in g for x in ("memory", "memgpt", "rag", "graph")):
            fallbacks.append("agent memory RAG language:python")
            fallbacks.append("graphrag language:python")
        if any(x in g for x in ("prompt", "superprompt", "agent")):
            fallbacks.append("llm agent framework language:python")
        if any(x in g for x in ("ads", "shopify", "marketing")):
            fallbacks.append("shopify marketing ads language:python")
        fallbacks.append("autonomous agent tools language:python")
        for f in fallbacks:
            if f not in queries:
                queries.append(f)
        return queries[:5]

    def _hf_queries(self, goal: str) -> List[str]:
        kws = self._keywords(goal)
        queries = []
        if kws:
            queries.append(" ".join(kws[:3]))
            queries.append(kws[0])
        g = goal.lower()
        if any(x in g for x in ("agent", "tool", "memory", "prompt")):
            queries.extend(["instruction tuning", "agent trajectory", "tool use"])
        if any(x in g for x in ("rag", "graph", "retrieval")):
            queries.extend(["retrieval augmented generation", "rag"])
        queries.append("text generation")
        # dedupe
        out, seen = [], set()
        for q in queries:
            if q not in seen:
                seen.add(q)
                out.append(q)
        return out[:5]

    def _skill_name(self, goal: str) -> str:
        words = re.findall(r"[a-zA-Z0-9]+", goal.lower())
        stop = {"grow", "learn", "from", "the", "a", "an", "and", "or", "to", "for", "my", "me", "self"}
        parts = [w for w in words if w not in stop][:4] or ["capability"]
        return "grown_" + "_".join(parts)[:40]

    def _synthesize_skill(
        self,
        goal: str,
        skill_name: str,
        gh: dict,
        models: dict,
        datasets: dict,
    ) -> str:
        repos = [r.get("full_name") for r in (gh.get("results") or [])[:5]]
        model_ids = [r.get("id") for r in (models.get("results") or [])[:5]]
        ds_ids = [r.get("id") for r in (datasets.get("results") or [])[:5]]
        readme_excerpt = ""
        if gh.get("readmes"):
            readme_excerpt = (gh["readmes"][0] or "")[:1500].replace('"""', "'''")

        class_name = "".join(p.title() for p in skill_name.split("_"))
        return f'''"""
Auto-grown skill: {skill_name}
Goal: {goal}
Generated by Prometheous GrowthAgent from GitHub + HuggingFace research.
"""
from __future__ import annotations
from typing import Any, Dict

# Discovered references (research-time)
GITHUB_REPOS = {repos!r}
HF_MODELS = {model_ids!r}
HF_DATASETS = {ds_ids!r}

README_EXCERPT = """{readme_excerpt[:1200]}"""


class {class_name}:
    name = "{skill_name}"
    role = "GrownSkill"
    specialty = {goal[:120]!r}
    tasks_completed = 0

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        query = str(payload.get("user_msg") or payload.get("query") or payload.get("goal") or "")
        lines = [
            f"🟠 Grown skill: {{self.name}}",
            f"Goal this skill was grown for: {goal[:200]}",
            "",
            "GitHub references:",
        ]
        for r in GITHUB_REPOS:
            lines.append(f"  • {{r}}")
        lines.append("HF models:")
        for m in HF_MODELS:
            lines.append(f"  • {{m}}")
        lines.append("HF datasets:")
        for d in HF_DATASETS:
            lines.append(f"  • {{d}}")
        lines += [
            "",
            f"Your request: {{query[:300]}}",
            "",
            "This skill is a research-backed scaffold. Re-run /grow to refresh sources.",
            "Enable PROM_SELF_GROW_INSTALL=1 to auto-register grown skills as agents.",
        ]
        if README_EXCERPT.strip():
            lines += ["", "Top README excerpt:", README_EXCERPT[:800]]
        return {{
            "status": "ok",
            "agent": self.name,
            "github_repos": GITHUB_REPOS,
            "hf_models": HF_MODELS,
            "hf_datasets": HF_DATASETS,
            "formatted": "\\n".join(lines),
        }}
'''

    def _install_skill(self, skill_name: str, body: str) -> dict:
        """Write into agents/ and register with orchestrator if running."""
        dest = ROOT / "agents" / f"{skill_name}.py"
        try:
            dest.write_text(body, encoding="utf-8")
            # dynamic register
            try:
                from core.orchestrator import orchestrator
                import importlib.util

                spec = importlib.util.spec_from_file_location(f"agents.{skill_name}", dest)
                mod = importlib.util.module_from_spec(spec)
                assert spec.loader
                spec.loader.exec_module(mod)
                # find class with name attr
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if isinstance(obj, type) and getattr(obj, "name", None) == skill_name:
                        orchestrator.register_agent(skill_name, obj())
                        return {"status": "ok", "path": str(dest), "registered": skill_name}
            except Exception as e:
                return {"status": "ok", "path": str(dest), "registered": False, "register_error": str(e)}
            return {"status": "ok", "path": str(dest), "registered": False}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _format(
        self,
        goal: str,
        skill_name: str,
        skill_path: Path,
        gh: dict,
        models: dict,
        datasets: dict,
        artifacts: list,
        installed: Optional[dict],
        steps: list,
    ) -> str:
        lines = [
            "🟠 Self-growth complete (figured out + packaged)",
            "",
            f"Goal: {goal[:200]}",
            f"Skill: {skill_name}",
            f"Written: {skill_path}",
            "",
            "GitHub:",
        ]
        for r in (gh.get("results") or [])[:5]:
            lines.append(f"  • {r.get('full_name')} ★{r.get('stars')} — {(r.get('description') or '')[:80]}")
        lines.append("HuggingFace models:")
        for m in (models.get("results") or [])[:5]:
            lines.append(f"  • {m.get('id')} ({m.get('pipeline_tag')})")
        lines.append("HuggingFace datasets:")
        for d in (datasets.get("results") or [])[:5]:
            lines.append(f"  • {d.get('id')}")
        lines.append("")
        lines.append("Artifacts:")
        for a in artifacts:
            lines.append(f"  • {a}")
        if installed:
            lines.append(f"Install: {installed}")
        else:
            lines.append("Install: dry (set PROM_SELF_GROW_INSTALL=1 to drop into agents/)")
        lines.append("")
        lines.append("Next: /grow <another skill> · rebuild finetune: python scripts/build_finetune_dataset.py")
        return "\n".join(lines)
