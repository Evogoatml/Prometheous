"""
MCP — minimal in-process tool server for Prometheous.

This is not an external JSON-RPC/TCP server. It is a local function
dispatch that exposes a small, validated tool surface:

- ping
- fs.exists / fs.read / fs.write
- http.get
- shell.run (limited)

From the agent perspective, this is the MCP boundary:
in-process calls only, no network exposure, no shell by default.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.sandbox import ROOT, resolve_project_path, run_shell


class ToolRegistry:
    tools: Dict[str, Any] = {}

    @classmethod
    def register(cls, name: str):
        def decorator(fn):
            cls.tools[name] = fn
            return fn
        return decorator

    @classmethod
    def execute(cls, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if name not in cls.tools:
            return {"error": f"unknown tool: {name}"}
        try:
            return cls.tools[name](**(arguments or {}))
        except TypeError as e:
            return {"error": f"invalid arguments: {e}"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}


@ToolRegistry.register("tools.list")
def tool_tools_list() -> Dict[str, Any]:
    from mcp.schemas import list_tool_schemas
    names = sorted(ToolRegistry.tools.keys())
    return {"status": "ok", "registered": names, "schemas": list_tool_schemas()}


@ToolRegistry.register("ping")
def tool_ping() -> Dict[str, Any]:
    return {"pong": True}


@ToolRegistry.register("fs.exists")
def tool_fs_exists(path: str) -> Dict[str, Any]:
    resolved, err = resolve_project_path(path)
    if err:
        return {"error": err}
    return {"exists": resolved.exists(), "path": str(resolved)}


@ToolRegistry.register("fs.read")
def tool_fs_read(path: str, max_bytes: int = 200_000) -> Dict[str, Any]:
    resolved, err = resolve_project_path(path, must_exist=True)
    if err:
        return {"error": err}
    p = resolved
    data = p.read_bytes()[:max_bytes]
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        return {"error": f"decode failed: {e}"}
    return {"path": str(p.resolve()), "bytes": len(data), "text": text}


@ToolRegistry.register("fs.folder_context")
def tool_fs_folder_context(
    path: str,
    max_files: int = 200,
    recursive: bool = True,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """On-demand folder index — single folder only, no repo-wide scan."""
    try:
        from knowledge.folder_index import scan_folder
        return scan_folder(
            path,
            root=ROOT,
            max_files=max_files,
            recursive=recursive,
            use_cache=use_cache,
        )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "path": path}


@ToolRegistry.register("healing.list")
def tool_healing_list(limit: int = 5) -> Dict[str, Any]:
    from learning.healing import recent_proposals
    entries = recent_proposals(limit=limit)
    return {"status": "ok", "count": len(entries), "proposals": entries}


@ToolRegistry.register("healing.apply_worktree")
def tool_healing_apply_worktree(proposal_id: str, proposal_index: int = 0) -> Dict[str, Any]:
    from learning.healing import apply_worktree
    return apply_worktree(proposal_id, proposal_index=proposal_index)


@ToolRegistry.register("healing.apply_live")
def tool_healing_apply_live(proposal_id: str, proposal_index: int = 0) -> Dict[str, Any]:
    from learning.healing import apply_live
    return apply_live(proposal_id, proposal_index=proposal_index)


@ToolRegistry.register("fs.write")
def tool_fs_write(path: str, text: str, mode: str = "w") -> Dict[str, Any]:
    resolved, err = resolve_project_path(path)
    if err:
        return {"error": err}
    p = resolved
    p.parent.mkdir(parents=True, exist_ok=True)
    if "b" in mode:
        p.write_bytes(text.encode("utf-8", errors="replace") if isinstance(text, str) else text)
    else:
        p.write_text(text, encoding="utf-8")
    return {"written": str(p.resolve()), "bytes": len(text)}


@ToolRegistry.register("web.search")
def tool_web_search(query: str, num_results: int = 5) -> Dict[str, Any]:
    from tools.web_search import search_web
    return search_web(query, num_results=num_results)


@ToolRegistry.register("http.get")
def tool_http_get(url: str, max_bytes: int = 200_000) -> Dict[str, Any]:
    if not re.match(r"^https?://", url):
        return {"error": f"unsupported url scheme: {url}"}
    req = urllib.request.Request(url, headers={"User-Agent": "Prometheous-MCP/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()[:max_bytes]
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "url": url}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "url": url}
    return {"url": url, "bytes": len(body), "body": body.decode("utf-8", errors="replace")}


@ToolRegistry.register("shell.run")
def tool_shell_run(command: str, cwd: str = "") -> Dict[str, Any]:
    """Restricted argv-based runner (no shell=True)."""
    return run_shell(command, cwd=cwd)


@ToolRegistry.register("github.search")
def tool_github_search(query: str, limit: int = 5) -> Dict[str, Any]:
    from tools.github_api import search_repositories

    return search_repositories(query, limit=limit)


@ToolRegistry.register("github.readme")
def tool_github_readme(owner: str, repo: str) -> Dict[str, Any]:
    from tools.github_api import get_readme

    return get_readme(owner, repo)


@ToolRegistry.register("github.file")
def tool_github_file(owner: str, repo: str, path: str, ref: str = "") -> Dict[str, Any]:
    from tools.github_api import get_file

    return get_file(owner, repo, path, ref=ref)


@ToolRegistry.register("hf.search_models")
def tool_hf_search_models(query: str, limit: int = 5) -> Dict[str, Any]:
    from tools.huggingface_api import search_models

    return search_models(query, limit=limit)


@ToolRegistry.register("hf.search_datasets")
def tool_hf_search_datasets(query: str, limit: int = 5) -> Dict[str, Any]:
    from tools.huggingface_api import search_datasets

    return search_datasets(query, limit=limit)


@ToolRegistry.register("hf.pull_dataset")
def tool_hf_pull_dataset(dataset_id: str, split: str = "train", max_rows: int = 50) -> Dict[str, Any]:
    from tools.huggingface_api import pull_dataset_rows

    return pull_dataset_rows(dataset_id, split=split, max_rows=max_rows)


class MCPClient:
    @staticmethod
    def call(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return ToolRegistry.execute(name, arguments)
