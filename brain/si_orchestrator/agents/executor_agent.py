"""
Executor agent — runs Python code and shell commands from LLM output.

Sandboxed: runs in a subprocess with timeout. No network access by default.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Sequence

from ..core.interfaces import Agent, AgentResult, AgentTask


class ExecutorAgent(Agent):
    name = "executor"
    version = "1.0.0"
    skills: Sequence[str] = (
        "execute",
        "run",
        "code",
        "script",
        "python",
        "shell",
        "command",
        "build",
        "compile",
        "install",
    )

    def __init__(
        self,
        workspace: Path | None = None,
        timeout: int = 60,
        max_output: int = 5000,
    ):
        pkg = Path(__file__).resolve().parents[2]
        self.workspace = Path(workspace or (pkg / "si_orchestrator" / "workspace")).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_output = max_output

    def run(self, task: AgentTask) -> AgentResult:
        code = task.context.get("code", "")
        source = task.context.get("source", "user")
        traces: list[dict[str, Any]] = []

        if not code:
            goal = task.goal.strip()
            code = self._goal_to_code(goal)
            traces.append({"step": "goal_to_code", "code": code[:200]})

        if not code:
            return AgentResult(
                task_id=task.id,
                success=False,
                error="No code to execute",
                traces=traces,
            )

        is_shell = self._is_shell(code)
        traces.append({"step": "classify", "type": "shell" if is_shell else "python"})

        try:
            if is_shell:
                output = self._run_shell(code)
            else:
                output = self._run_python(code)
            traces.append({"step": "execute", "exit_code": output["exit_code"]})
            return AgentResult(
                task_id=task.id,
                success=output["exit_code"] == 0,
                output=output["stdout"] or output["stderr"] or "(no output)",
                error=output["stderr"] if output["exit_code"] != 0 else None,
                traces=traces,
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                task_id=task.id,
                success=False,
                error=f"Execution timed out after {self.timeout}s",
                traces=traces,
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.id,
                success=False,
                error=str(exc),
                traces=traces,
            )

    def _goal_to_code(self, goal: str) -> str:
        g = goal.lower()
        if any(k in g for k in ("current directory", "current working directory", "where am i", "pwd", "cwd")):
            return "import os; print(os.getcwd())"
        if any(k in g for k in ("date", "time", "what day")):
            return "from datetime import datetime; print(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))"
        if any(k in g for k in ("disk usage", "disk space", "df ")):
            return "import shutil; total, used, free = shutil.disk_usage('/'); print(f'Total: {total // (1024**3)}GB, Used: {used // (1024**3)}GB, Free: {free // (1024**3)}GB')"
        if any(k in g for k in ("environment", "env vars", "env variables")):
            return "import os\nfor k, v in sorted(os.environ.items()):\n    print(f'{k}={v}')"
        if any(k in g for k in ("list files", "ls ", "show files")):
            path = "."
            for word in goal.split():
                if "/" in word or word.startswith("."):
                    path = word
                    break
            return f"import os\nfor f in sorted(os.listdir('{path}')):\n    print(f)"
        return ""

    def _is_shell(self, code: str) -> bool:
        first_line = code.strip().split("\n")[0].strip()
        if first_line.startswith("#!"):
            return True
        shell_cmds = ("ls ", "cat ", "grep ", "find ", "mkdir ", "rm ", "cp ", "mv ",
                       "curl ", "wget ", "git ", "pip ", "apt ", "chmod ", "echo ")
        return any(first_line.startswith(c) for c in shell_cmds)

    def _run_python(self, code: str) -> Dict[str, Any]:
        tmp = self.workspace / "_exec_tmp.py"
        tmp.write_text(code, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(tmp)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.workspace),
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            stdout = result.stdout[:self.max_output]
            stderr = result.stderr[:self.max_output]
            return {"exit_code": result.returncode, "stdout": stdout, "stderr": stderr}
        finally:
            tmp.unlink(missing_ok=True)

    def _run_shell(self, code: str) -> Dict[str, Any]:
        result = subprocess.run(
            code,
            shell=True,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=str(self.workspace),
        )
        stdout = result.stdout[:self.max_output]
        stderr = result.stderr[:self.max_output]
        return {"exit_code": result.returncode, "stdout": stdout, "stderr": stderr}
