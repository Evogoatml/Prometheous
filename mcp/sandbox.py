"""
Project-root sandbox for MCP filesystem and shell tools.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

_SHELL_META: Dict[str, Dict[str, Any]] = {
    "pwd": {"max_args": 0},
    "whoami": {"max_args": 0},
    "id": {"max_args": 0},
    "uname": {"max_args": 2},
    "date": {"max_args": 2},
    "ls": {"max_args": 12},
    "cat": {"max_args": 8, "path_args_from": 1},
    "head": {"max_args": 8, "path_args_from": 1, "flags": {"-n"}},
    "tail": {"max_args": 8, "path_args_from": 1, "flags": {"-n"}},
    "grep": {"max_args": 16, "path_args_from": 2},
    "find": {"max_args": 16, "path_args_from": 1, "deny_flags": {"-exec", "-execdir", "-delete"}},
    "git": {"max_args": 24, "git_subcommands": {"status", "log", "diff", "rev-parse", "branch", "show"}},
    "python": {"max_args": 16, "script_from": 1, "deny_flags": {"-c", "-m"}},
    "python3": {"max_args": 16, "script_from": 1, "deny_flags": {"-c", "-m"}},
}

_META_CHARS = re.compile(r"[;|&$`<>]")


def resolve_project_path(path: str, *, must_exist: bool = False) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve path under project ROOT. Rejects traversal and absolute escapes."""
    raw = (path or "").strip().strip("`\"'")
    if not raw:
        return None, "empty path"
    if _META_CHARS.search(raw):
        return None, "path contains shell/meta characters"

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (ROOT / candidate)
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return None, "path outside project root"
    except Exception as exc:
        return None, f"invalid path: {exc}"

    if must_exist and not resolved.exists():
        return None, f"missing file: {path}"
    return resolved, None


def resolve_project_cwd(cwd: str = "") -> Tuple[Path, Optional[str]]:
    if not cwd:
        return ROOT.resolve(), None
    resolved, err = resolve_project_path(cwd, must_exist=True)
    if err:
        return ROOT.resolve(), err
    if not resolved.is_dir():
        return ROOT.resolve(), "cwd is not a directory"
    return resolved, None


def _is_flag(token: str, flags: set[str]) -> bool:
    return token in flags or any(token.startswith(f + "=") for f in flags)


def build_shell_argv(command: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """Parse a safe argv list for subprocess (shell=False)."""
    raw = (command or "").strip()
    if not raw or _META_CHARS.search(raw):
        return None, "command contains shell metacharacters"

    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        return None, f"invalid command: {exc}"
    if not argv:
        return None, "empty command"

    base = argv[0]
    meta = _SHELL_META.get(base)
    if meta is None:
        allowed = ", ".join(sorted(_SHELL_META))
        return None, f"command not allowed: {base}. Allowed: {allowed}"

    if len(argv) - 1 > int(meta.get("max_args", 0)):
        return None, f"too many arguments for {base}"

    deny_flags = set(meta.get("deny_flags") or ())
    flags = set(meta.get("flags") or ())
    for token in argv[1:]:
        if token in deny_flags or token.split("=", 1)[0] in deny_flags:
            return None, f"flag not allowed for {base}: {token}"

    if base == "git":
        subs = meta.get("git_subcommands") or set()
        if len(argv) < 2 or argv[1] not in subs:
            return None, f"git subcommand not allowed. Allowed: {', '.join(sorted(subs))}"

    script_from = meta.get("script_from")
    if script_from is not None:
        if len(argv) <= script_from:
            return None, f"{base} requires a script path under project root"
        script, err = resolve_project_path(argv[script_from], must_exist=True)
        if err:
            return None, err
        argv[script_from] = str(script)

    path_from = meta.get("path_args_from")
    if path_from is not None:
        i = path_from
        while i < len(argv):
            token = argv[i]
            if _is_flag(token, flags) or (token.startswith("-") and token[1:].isdigit()):
                i += 1
                if "=" not in token and i < len(argv) and not argv[i].startswith("-"):
                    i += 1
                continue
            resolved, err = resolve_project_path(token, must_exist=False)
            if err:
                return None, err
            argv[i] = str(resolved)
            i += 1

    return argv, None


def run_shell(command: str, cwd: str = "", timeout: int = 120) -> Dict[str, Any]:
    argv, err = build_shell_argv(command)
    if err:
        return {"error": err}
    workdir, cwd_err = resolve_project_cwd(cwd)
    if cwd_err:
        return {"error": cwd_err}
    try:
        result = subprocess.run(
            argv,
            shell=False,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return {"error": str(exc)}
    return {
        "command": command,
        "argv": argv,
        "cwd": str(workdir),
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-2000:],
    }