"""
Navigator agent — stateful system navigation and command creation.

Maintains a persistent shell session (cwd, env, history) for filesystem
traversal, process/system inspection, network exploration, and dynamic
script/tool generation.  New commands are written to ~/.prom/bin/ and
that directory is added to PATH so they become available immediately.
"""

from __future__ import annotations

import os
import re
import stat
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..core.interfaces import Agent, AgentResult, AgentTask


# ---------------------------------------------------------------------------
# Persistent shell session
# ---------------------------------------------------------------------------

class ShellSession:
    """Stateful shell — preserves cwd, environment, and command history."""

    def __init__(self, cwd: str | Path, env: dict[str, str] | None = None):
        self.cwd = Path(cwd).resolve()
        self.env = (env or os.environ).copy()
        self.history: list[dict[str, Any]] = []

    def run(
        self,
        command: str,
        *,
        timeout: int = 60,
        max_output: int = 10_000,
    ) -> dict[str, Any]:
        start = time.time()
        raw = command.strip()

        # --- built-in cd ---------------------------------------------------
        if raw.startswith("cd "):
            target = raw[3:].strip()
            return self._handle_cd(target)

        if raw == "cd":
            return {"exit_code": 0, "stdout": str(self.cwd), "stderr": ""}

        # --- run everything else via subprocess ----------------------------
        try:
            result = subprocess.run(
                raw,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.cwd),
                env=self.env,
            )
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stdout": "", "stderr": f"Timeout ({timeout}s)"}
        except Exception as exc:
            return {"exit_code": -1, "stdout": "", "stderr": str(exc)}

        stdout = result.stdout[:max_output]
        stderr = result.stderr[:max_output]
        elapsed = time.time() - start

        entry: dict[str, Any] = {
            "command": raw,
            "exit_code": result.returncode,
            "elapsed": round(elapsed, 3),
        }
        self.history.append(entry)
        if len(self.history) > 500:
            self.history.pop(0)

        return {
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "cwd": str(self.cwd),
            "elapsed": round(elapsed, 3),
        }

    def _handle_cd(self, target: str) -> dict[str, Any]:
        expanded = os.path.expanduser(target)
        candidate = (self.cwd / expanded).resolve() if not Path(expanded).is_absolute() else Path(expanded).resolve()
        if candidate.is_dir():
            self.cwd = candidate
            return {"exit_code": 0, "stdout": f"→ {self.cwd}", "stderr": ""}
        return {"exit_code": 1, "stdout": "", "stderr": f"cd: no such directory: {target}"}


# ---------------------------------------------------------------------------
# Navigator agent
# ---------------------------------------------------------------------------

class NavigatorAgent(Agent):
    name = "navigator"
    version = "1.0.0"
    skills: Sequence[str] = (
        "navigate",
        "explore",
        "ls",
        "cd",
        "find",
        "locate",
        "tree",
        "ps",
        "df",
        "du",
        "free",
        "uname",
        "uptime",
        "network",
        "scan",
        "ping",
        "curl",
        "wget",
        "script",
        "command",
        "tool",
        "alias",
        "env",
        "system",
        "process",
        "disk",
    )

    def __init__(
        self,
        workspace: Path | None = None,
        bin_dir: Path | None = None,
        allowed_roots: list[Path] | None = None,
        timeout: int = 60,
        max_output: int = 10_000,
        allow_network: bool = True,
    ):
        pkg = Path(__file__).resolve().parents[2]
        self.workspace = Path(workspace or (pkg / "si_orchestrator" / "workspace")).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.bin_dir = Path(bin_dir or (Path.home() / ".prom" / "bin")).resolve()
        self.bin_dir.mkdir(parents=True, exist_ok=True)

        # Prepend bin_dir to PATH in the session
        env = os.environ.copy()
        current_path = env.get("PATH", "")
        if str(self.bin_dir) not in current_path:
            env["PATH"] = f"{self.bin_dir}:{current_path}"

        self.session = ShellSession(cwd=self.workspace, env=env)
        self.timeout = timeout
        self.max_output = max_output
        self.allow_network = allow_network

        # Default sandbox roots — restrict where the agent can write scripts
        self.allowed_roots = [p.resolve() for p in (allowed_roots or [
            self.workspace,
            self.bin_dir,
            pkg,
            pkg.parent,  # Prometheous project
        ])]

    # ------------------------------------------------------------------
    # Agent interface
    # ------------------------------------------------------------------

    def run(self, task: AgentTask) -> AgentResult:
        goal = task.goal.strip()
        traces: list[dict[str, Any]] = []
        context_cmd = (task.context or {}).get("command", "")

        # 1. If the LLM passed an explicit shell command, run it directly
        if context_cmd:
            return self._exec(context_cmd, traces, task.id)

        # 2. Classify the goal and generate command(s)
        action = self._classify(goal)
        traces.append({"step": "classify", "action": action})

        try:
            if action == "script":
                return self._create_script(goal, traces, task.id)
            if action == "tool":
                return self._create_tool(goal, traces, task.id)
            if action == "multi":
                commands = self._parse_multi(goal)
                traces.append({"step": "multi", "count": len(commands)})
                return self._run_commands(commands, traces, task.id)

            command = self._goal_to_command(goal, action)
            traces.append({"step": "command", "command": command[:200]})
            return self._exec(command, traces, task.id)

        except Exception as exc:
            return AgentResult(
                task_id=task.id,
                success=False,
                error=str(exc),
                traces=traces,
            )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(self, goal: str) -> str:
        g = goal.lower()
        if any(k in g for k in ("create script", "write script", "make script", "new script")):
            return "script"
        if any(k in g for k in ("create command", "new command", "make tool", "install tool",
                                 "create tool", "new tool")):
            return "tool"
        if ";" in g or "&&" in g:
            return "multi"
        if "then " in g and any(cmd in g for cmd in ("cd", "ls", "cat", "find", "grep", "ps", "df")):
            return "multi"
        return "single"

    # ------------------------------------------------------------------
    # Goal → command translation
    # ------------------------------------------------------------------

    def _goal_to_command(self, goal: str, action: str) -> str:
        g = goal.lower().strip()

        # Filesystem
        if re.match(r"^(ls|list)\b", g):
            path = self._extract_path(goal) or "."
            flags = "-la" if "all" in g or "hidden" in g else ""
            if "tree" in g or "recursive" in g or "recurs" in g:
                return f"find {shlex.quote(path)} -maxdepth 2 | head -80"
            if "sort" in g and "size" in g:
                return f"ls -lhS {shlex.quote(path)}"
            return f"ls {flags} {shlex.quote(path)}".strip()

        if re.match(r"^(cd|change.d(ir|irectory)?)\b", g):
            after_cd = re.sub(r"^(?:cd|change\s+directory)\s+", "", goal, flags=re.I).strip()
            target = self._extract_path(after_cd)
            if not target and after_cd:
                target = after_cd.split()[0]
            target = (target or "~").strip("'\"")
            return f"cd {shlex.quote(target)}"

        if re.match(r"^(pwd|where.am|current.directory)\b", g):
            return "pwd"

        if re.match(r"^(cat|read|show|display|print|head|tail)\b", g):
            path = self._extract_path(goal)
            if not path:
                return goal  # let shell try
            if "head" in g or "first" in g:
                n = self._extract_number(g) or 10
                return f"head -n {n} {shlex.quote(path)}"
            if "tail" in g or "last" in g:
                n = self._extract_number(g) or 10
                return f"tail -n {n} {shlex.quote(path)}"
            return f"cat {shlex.quote(path)}"

        if re.match(r"^(find|search|grep|locate)\b", g):
            pattern = self._extract_pattern(goal)
            path = self._extract_path(goal) or "."
            if not pattern:
                return f"find {shlex.quote(path)} -maxdepth 3 | head -50"
            if "name" in g or "filename" in g:
                return f"find {shlex.quote(path)} -iname '*{pattern}*' 2>/dev/null | head -30"
            if "content" in g or "text" in g or "grep" in g:
                return f"grep -rl '{pattern}' {shlex.quote(path)} 2>/dev/null | head -30"
            return f"find {shlex.quote(path)} -iname '*{pattern}*' 2>/dev/null | head -30"

        if re.match(r"^(mkdir|make.directory|create.directory)\b", g):
            path = self._extract_path(goal) or "new_dir"
            return f"mkdir -p {shlex.quote(path)}"

        if re.match(r"^(tree)\b", g):
            path = self._extract_path(goal) or "."
            depth = self._extract_number(g) or 2
            return f"find {shlex.quote(path)} -maxdepth {depth} | head -100"

        if re.match(r"^(du|disk.usage|size)\b", g):
            path = self._extract_path(goal) or "."
            if "sort" in g or "largest" in g:
                return f"du -sh {shlex.quote(path)}/* 2>/dev/null | sort -rh | head -20"
            return f"du -sh {shlex.quote(path)}"

        if re.match(r"^(df|disk.(free|space))\b", g):
            return "df -h"

        # System / process
        if re.match(r"^(ps|process|running)\b", g):
            if "all" in g or "every" in g:
                return "ps aux | head -40"
            return "ps aux --sort=-%mem | head -20"

        if re.match(r"^(free|memory|ram)\b", g):
            return "free -h"

        if re.match(r"^(uname|system.info|kernel)\b", g):
            return "uname -a"

        if re.match(r"^(uptime)\b", g):
            return "uptime"

        if re.match(r"^(env|environment)\b", g):
            if "var" in g or "variable" in g:
                var = self._extract_var(goal)
                return f"echo ${var}" if var else "env | sort"
            return "env | sort"

        if re.match(r"^(whoami|user|who)\b", g):
            return "whoami"

        # Network
        if re.match(r"^(ping|network|connectivity)\b", g):
            target = self._extract_host(goal) or "8.8.8.8"
            return f"ping -c 4 {target}"

        if re.match(r"^(curl|fetch|download|http.get)\b", g):
            url = self._extract_url(goal)
            if not url:
                return goal
            return f"curl -sI {url} | head -20"

        if re.match(r"^(ss|netstat|ports|listening)\b", g):
            return "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null | head -20"

        # Fallback — let the shell try to interpret it
        return goal

    # ------------------------------------------------------------------
    # Multi-command execution
    # ------------------------------------------------------------------

    def _parse_multi(self, goal: str) -> list[str]:
        """Split goal into sequential commands on ; or &&."""
        commands: list[str] = []
        for sep in (" && ", " ; ", "\n"):
            parts = goal.split(sep)
            if len(parts) > 1:
                commands = [p.strip() for p in parts if p.strip()]
                break
        if not commands:
            # Heuristic: look for patterns like "cd X then Y then Z"
            parts = re.split(r"\b(then|and then|next|after that)\b", goal, flags=re.I)
            commands = [p.strip() for p in parts if p.strip() and p.strip().lower() not in (
                "then", "and then", "next", "after that"
            )]
        if not commands:
            commands = [goal]
        return commands

    def _run_commands(
        self, commands: list[str], traces: list[dict], task_id: str,
    ) -> AgentResult:
        outputs: list[dict[str, Any]] = []
        for i, cmd in enumerate(commands):
            result = self.session.run(cmd, timeout=self.timeout)
            outputs.append({
                "command": cmd,
                "exit_code": result["exit_code"],
                "stdout": result["stdout"][:2000],
                "stderr": result["stderr"][:500],
            })
            traces.append({"step": f"cmd_{i}", "command": cmd[:100], "exit_code": result["exit_code"]})
            if result["exit_code"] != 0:
                break
        return AgentResult(
            task_id=task_id,
            success=True,
            output={"commands": outputs, "cwd": str(self.session.cwd)},
            traces=traces,
        )

    # ------------------------------------------------------------------
    # Single command execution
    # ------------------------------------------------------------------

    def _exec(self, command: str, traces: list[dict], task_id: str) -> AgentResult:
        result = self.session.run(command, timeout=self.timeout, max_output=self.max_output)
        traces.append({
            "step": "exec",
            "exit_code": result["exit_code"],
            "elapsed": result.get("elapsed"),
        })
        return AgentResult(
            task_id=task_id,
            success=result["exit_code"] == 0,
            output={
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "cwd": result.get("cwd", str(self.session.cwd)),
                "exit_code": result["exit_code"],
                "history_count": len(self.session.history),
            },
            error=result["stderr"] if result["exit_code"] != 0 else None,
            traces=traces,
        )

    # ------------------------------------------------------------------
    # Script and command creation
    # ------------------------------------------------------------------

    def _create_script(self, goal: str, traces: list[dict], task_id: str) -> AgentResult:
        name = self._extract_name(goal) or "script.sh"
        if not name.endswith((".sh", ".py", ".bash", ".js", ".rb")):
            name = f"{name}.sh"
        content = self._extract_code(goal)
        if not content:
            content = "#!/usr/bin/env bash\n# Auto-generated by NavigatorAgent\n\n"

        path = self.workspace / name
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        traces.append({"step": "create_script", "path": str(path)})
        return AgentResult(
            task_id=task_id,
            success=True,
            output={"path": str(path), "size": len(content), "executable": True},
            traces=traces,
        )

    def _create_tool(self, goal: str, traces: list[dict], task_id: str) -> AgentResult:
        name = self._extract_name(goal) or "tool"
        path = self.bin_dir / name
        content = self._extract_code(goal)
        if not content:
            content = (
                "#!/usr/bin/env bash\n"
                f"# NavigatorAgent tool: {name}\n"
                'echo "Usage: {name} [args]"'
            )

        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        traces.append({"step": "create_tool", "path": str(path)})
        return AgentResult(
            task_id=task_id,
            success=True,
            output={
                "path": str(path),
                "size": len(content),
                "executable": True,
                "installed_in_path": str(self.bin_dir),
            },
            traces=traces,
        )

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    _PATH_RE = re.compile(
        r"(?:path\s+)?['\"]?((?:/(?:[\w.\-]+/?){1,}|~?[\w./\-]+(?:/[\w.\-]+)+|[\w.\-]+))['\"]?"
    )
    _QUOTED_PATH_RE = re.compile(r"['\"]((?:/(?:[\w.\-]+/?){1,}|\.?[\w./\-]+(?:/[\w.\-]+)+))['\"]")
    _NUMBER_RE = re.compile(r"\b(\d+)\b")
    _PATTERN_RE = re.compile(r"(?:pattern|for|matching|containing)\s+['\"]?(\w+)['\"]?", re.I)
    _QUOTED_RE = re.compile(r"['\"](\w+)['\"]")
    _NAME_RE = re.compile(r"(?:called|named|as)\s+['\"]?(\w[\w.\-]*)['\"]?", re.I)
    _VAR_RE = re.compile(r"(?:var|variable)\s+['\"]?(\w+)['\"]?", re.I)
    _HOST_RE = re.compile(r"(?:host|to|target)\s+['\"]?([\w.\-]+(?:\.[\w.\-]+)+)['\"]?", re.I)
    _URL_RE = re.compile(r"(https?://[^\s)'\"]+)", re.I)
    _CODE_BLOCK_RE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.S)

    def _extract_path(self, goal: str) -> str | None:
        m = self._QUOTED_PATH_RE.search(goal)
        if m:
            return m.group(1)
        m = self._PATH_RE.search(goal)
        if m:
            return m.group(1)
        return None

    def _extract_number(self, goal: str) -> int | None:
        m = self._NUMBER_RE.search(goal)
        return int(m.group(1)) if m else None

    def _extract_pattern(self, goal: str) -> str | None:
        m = self._PATTERN_RE.search(goal)
        if m:
            return m.group(1)
        m = self._QUOTED_RE.search(goal)
        if m and m.group(1) not in ("ls", "cd", "cat", "find", "grep"):
            return m.group(1)
        return None

    def _extract_name(self, goal: str) -> str | None:
        m = self._NAME_RE.search(goal)
        return m.group(1) if m else None

    def _extract_var(self, goal: str) -> str | None:
        m = self._VAR_RE.search(goal)
        return m.group(1) if m else None

    def _extract_host(self, goal: str) -> str | None:
        m = self._HOST_RE.search(goal)
        return m.group(1) if m else None

    def _extract_url(self, goal: str) -> str | None:
        m = self._URL_RE.search(goal)
        return m.group(1) if m else None

    def _extract_code(self, goal: str) -> str:
        m = self._CODE_BLOCK_RE.search(goal)
        if m:
            return m.group(1).strip()
        return ""



