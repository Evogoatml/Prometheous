"""
Sandbox dry-run gate for template-generated tool code.

Compiles and executes in a restricted namespace with timeout.
"""
from __future__ import annotations

import ast
import threading
from typing import Any, Callable, Dict, List, Optional, Set


BLOCKED_NAMES: Set[str] = {
    "os", "sys", "subprocess", "socket", "shutil", "pathlib",
    "importlib", "__import__", "eval", "exec", "compile", "open",
    "breakpoint", "globals", "locals", "getattr", "setattr", "delattr",
}

BLOCKED_ATTRS: Set[str] = {"system", "popen", "spawn", "fork", "execl"}


def _validate_ast(code: str) -> List[str]:
    issues: List[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax_error:{exc.msg}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BLOCKED_NAMES:
                    issues.append(f"blocked_import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in BLOCKED_NAMES and root not in _SAFE_IMPORT_ROOTS:
                    issues.append(f"blocked_import:{node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_NAMES:
                issues.append(f"blocked_call:{node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_ATTRS:
                issues.append(f"blocked_attr:{node.func.attr}")
    return issues


_SAFE_IMPORT_ROOTS = frozenset({"hashlib", "json", "urllib"})


def _safe_import(
    name: str,
    globals: Optional[Dict[str, Any]] = None,
    locals: Optional[Dict[str, Any]] = None,
    fromlist: tuple = (),
    level: int = 0,
):
    root = (name or "").split(".")[0]
    if root not in _SAFE_IMPORT_ROOTS:
        raise ImportError(f"blocked import: {name}")
    return __import__(name, globals, locals, fromlist, level)


def _restricted_builtins() -> Dict[str, Any]:
    return {
        "True": True,
        "False": False,
        "None": None,
        "int": int,
        "float": float,
        "str": str,
        "dict": dict,
        "list": list,
        "len": len,
        "range": range,
        "min": min,
        "max": max,
        "sum": sum,
        "enumerate": enumerate,
        "isinstance": isinstance,
        "type": type,
        "Exception": Exception,
        "__import__": _safe_import,
    }


def dry_run(
    code: str,
    *,
    entry: str = "run",
    test_args: Optional[Dict[str, Any]] = None,
    timeout_s: float = 5.0,
    invoke: bool = False,
) -> Dict[str, Any]:
    """
    Compile + execute template ``run()`` with restricted globals.

    Returns gate result dict with ``passed`` bool and ``checks`` list.
    """
    checks: List[str] = []
    ast_issues = _validate_ast(code)
    if ast_issues:
        return {"passed": False, "checks": ["ast:" + i for i in ast_issues]}

    try:
        compiled = compile(code, "<ghost_sentinel_template>", "exec")
    except SyntaxError as exc:
        return {"passed": False, "checks": [f"compile_error:{exc.msg}"]}

    namespace: Dict[str, Any] = {"__builtins__": _restricted_builtins()}
    result_box: Dict[str, Any] = {}
    error_box: Dict[str, str] = {}

    def _target() -> None:
        try:
            exec(compiled, namespace)  # noqa: S102 — gated sandbox only
            fn: Callable[..., Any] = namespace.get(entry)  # type: ignore[assignment]
            if not callable(fn):
                error_box["error"] = f"missing_entry:{entry}"
                return
            checks.append("sandbox_compile:ok")
            if not invoke:
                checks.append("sandbox_invoke:skipped")
                return
            args = test_args or {}
            result_box["result"] = fn(**args)
        except Exception as exc:  # noqa: BLE001
            error_box["error"] = f"runtime:{type(exc).__name__}:{exc}"

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)

    if thread.is_alive():
        return {"passed": False, "checks": ["sandbox_dry_run:TIMEOUT"]}

    if error_box:
        return {"passed": False, "checks": ["sandbox_dry_run:" + error_box["error"]]}

    checks.append("sandbox_dry_run:ok")
    if "result" in result_box:
        checks.append(f"sandbox_result:{type(result_box['result']).__name__}")
    return {"passed": True, "checks": checks, "result": result_box.get("result")}