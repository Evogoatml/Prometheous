"""
Sandbox tool agent — list/read/search under allowed roots only.

No network. No writes outside workspace. Used when goals need files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..core.interfaces import Agent, AgentResult, AgentTask


class ToolAgent(Agent):
    name = "tools"
    version = "1.0.0"
    skills: Sequence[str] = (
        "read",
        "file",
        "search",
        "list",
        "find",
        "ls",
        "open",
        "show",
        "cat",
        "grep",
        "tools",
    )

    def __init__(
        self,
        roots: Optional[List[Path]] = None,
        workspace: Optional[Path] = None,
        max_hits: int = 12,
        max_read_lines: int = 120,
    ):
        # Prometheous project root = parents of si_orchestrator package
        pkg = Path(__file__).resolve().parents[2]  # .../brain
        project = pkg.parent  # .../Prometheous
        self.workspace = Path(workspace or (pkg / "si_orchestrator" / "workspace"))
        self.workspace.mkdir(parents=True, exist_ok=True)
        default_roots = [
            project,
            pkg / "si_orchestrator",
            self.workspace,
        ]
        # optional: adaptive_crypto only if present (needed-from-convo, not whole dump)
        crypto = Path("/home/popi/convo/adaptive_crypto")
        if crypto.is_dir():
            default_roots.append(crypto)
        self.roots = [Path(r).resolve() for r in (roots or default_roots)]
        self.max_hits = max_hits
        self.max_read_lines = max_read_lines

    def run(self, task: AgentTask) -> AgentResult:
        goal = task.goal.strip()
        traces: List[Dict[str, Any]] = []
        action = self._classify(goal)
        traces.append({"step": "classify", "action": action})

        try:
            if action == "list":
                path = self._extract_path(goal) or str(self.roots[0])
                out = self._list(path)
            elif action == "read":
                path = self._extract_path(goal)
                if not path:
                    # search then read best hit
                    hits = self._search(self._query_from_goal(goal))
                    traces.append({"step": "search_for_read", "hits": len(hits)})
                    if not hits:
                        return AgentResult(
                            task_id=task.id,
                            success=False,
                            error="no path and no search hits",
                            traces=traces,
                        )
                    path = hits[0]["path"]
                out = self._read(path)
            else:
                q = self._query_from_goal(goal)
                hits = self._search(q)
                out = {"query": q, "hits": hits, "count": len(hits)}
            traces.append({"step": "done", "action": action})
            return AgentResult(
                task_id=task.id,
                success=True,
                output=out,
                traces=traces,
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(
                task_id=task.id,
                success=False,
                error=str(exc),
                traces=traces,
            )

    def _classify(self, goal: str) -> str:
        g = goal.lower()
        if any(k in g for k in ("list ", "ls ", "list files", "directory", "dir ")):
            return "list"
        if any(k in g for k in ("read ", "open ", "cat ", "show file", "show the file")):
            return "read"
        if re.search(r"\.(py|md|json|txt|toml)\b", g) and any(
            k in g for k in ("read", "open", "show", "what is in", "contents")
        ):
            return "read"
        return "search"

    def _query_from_goal(self, goal: str) -> str:
        q = goal
        for w in (
            "search for",
            "find",
            "look for",
            "grep",
            "locate",
            "where is",
            "read",
            "open",
            "show",
            "list",
        ):
            q = re.sub(re.escape(w), " ", q, flags=re.I)
        return re.sub(r"\s+", " ", q).strip() or goal

    def _extract_path(self, goal: str) -> Optional[str]:
        m = re.search(r"['\"]([^'\"]+\.[a-zA-Z0-9]+)['\"]", goal)
        if m:
            return m.group(1)
        m = re.search(
            r"((?:/home/[\w./\-]+|[\w./\-]+(?:/[\w.\-]+)+\.(?:py|md|json|txt|toml)))",
            goal,
        )
        if m:
            return m.group(1)
        m = re.search(r"(\b[\w\-./]+\.(?:py|md|json|txt|toml)\b)", goal)
        return m.group(1) if m else None

    def _allowed(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for root in self.roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _resolve(self, path: str) -> Path:
        raw = Path(os.path.expanduser(path))
        if raw.is_absolute():
            return raw
        for root in self.roots:
            cand = (root / raw).resolve()
            if cand.exists():
                return cand
            cand2 = root / raw.name
            if cand2.exists():
                return cand2.resolve()
        return (self.roots[0] / raw).resolve()

    def _list(self, path: str) -> Dict[str, Any]:
        p = self._resolve(path)
        if not self._allowed(p):
            raise PermissionError(f"list blocked outside sandbox: {p}")
        if not p.exists():
            raise FileNotFoundError(str(p))
        if p.is_file():
            return {"path": str(p), "type": "file"}
        entries = sorted(p.iterdir(), key=lambda x: x.name.lower())[:80]
        return {
            "path": str(p),
            "entries": [
                {"name": e.name, "type": "dir" if e.is_dir() else "file"}
                for e in entries
            ],
        }

    def _read(self, path: str) -> Dict[str, Any]:
        p = self._resolve(path)
        if not self._allowed(p):
            raise PermissionError(f"read blocked outside sandbox: {p}")
        if not p.is_file():
            raise FileNotFoundError(str(p))
        if p.stat().st_size > 1_500_000:
            raise ValueError("file too large")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        body = "\n".join(lines[: self.max_read_lines])
        return {
            "path": str(p),
            "lines": len(lines),
            "truncated": len(lines) > self.max_read_lines,
            "content": body,
        }

    def _search(self, query: str) -> List[Dict[str, Any]]:
        needle = (query or "").lower().strip()
        if not needle:
            return []
        # use first few tokens for speed
        toks = [t for t in re.findall(r"[a-z0-9_]{3,}", needle)][:6]
        if not toks:
            toks = [needle[:40]]
        hits: List[Dict[str, Any]] = []
        exts = {".py", ".md", ".json", ".txt", ".toml"}
        for root in self.roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in exts:
                    continue
                if any(part in {".git", "__pycache__", ".venv", "node_modules"} for part in path.parts):
                    continue
                if path.stat().st_size > 400_000:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                low = text.lower()
                if not any(t in low or t in path.name.lower() for t in toks):
                    continue
                line_no, snippet = 0, ""
                for i, line in enumerate(text.splitlines(), 1):
                    if any(t in line.lower() for t in toks):
                        line_no, snippet = i, line.strip()[:160]
                        break
                hits.append(
                    {
                        "path": str(path),
                        "line": line_no,
                        "snippet": snippet or path.name,
                    }
                )
                if len(hits) >= self.max_hits:
                    return hits
        return hits
