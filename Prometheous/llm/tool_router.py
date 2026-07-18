"""
Rule-based + optional LLM tool routing for Prometheous function calling.

Primary path: deterministic patterns → MCP ToolRegistry (no LLM required).
Optional: PROM_LLM_TOOL_SELECT=1 uses OpenAI tools API when rules miss.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from mcp.schemas import SCHEMA_BY_NAME

logger = logging.getLogger(__name__)

try:
    from utils.config import cfg
    ROOT = cfg.ROOT
except Exception:
    ROOT = Path(__file__).resolve().parents[1]

_URL_RE = re.compile(r"https?://[^\s<>\"']+")


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    source: str = "rules"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "confidence": self.confidence,
            "source": self.source,
        }


def _resolve_path(path: str) -> str:
    from mcp.sandbox import resolve_project_path
    resolved, err = resolve_project_path(path)
    if err or resolved is None:
        return path.strip().strip("`\"'")
    return str(resolved)


def _parse_kv_tail(tail: str) -> Dict[str, Any]:
    """Parse key=value pairs or JSON object tail."""
    tail = (tail or "").strip()
    if not tail:
        return {}
    if tail.startswith("{"):
        try:
            return json.loads(tail)
        except json.JSONDecodeError:
            pass
    out: Dict[str, Any] = {}
    for part in re.split(r"\s+", tail):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip().strip("\"'")
    return out


def classify_tool(text: str) -> Optional[ToolCall]:
    """Deterministic tool selection from user text."""
    raw = (text or "").strip()
    if not raw or raw.startswith("/"):
        return None
    lower = raw.lower()

    # Explicit: tool:fs.read path=main.py  OR  /tool web.search query=foo
    explicit = re.match(r"^(?:/tool|tool:)\s*([\w.]+)(?:\s+(.*))?$", raw, re.I)
    if explicit:
        name = explicit.group(1)
        if name in SCHEMA_BY_NAME:
            args = _parse_kv_tail(explicit.group(2) or "")
            return ToolCall(name, args, confidence=0.99, source="explicit")

    # Bare URL
    url_m = _URL_RE.search(raw)
    if url_m:
        url = url_m.group(0).rstrip(".,;)")
        triggers = ("fetch", "get", "curl", "download", "read url", "http", "https", "open url")
        if lower.strip() == url.lower() or any(t in lower for t in triggers):
            return ToolCall("http.get", {"url": url}, confidence=0.92, source="rules")

    # fs.write — create/save file when path + intent are clear
    write_m = re.search(
        r"\b(?:create|write|save|make)\s+(?:a\s+)?(?:new\s+)?"
        r"(?:file|script|module)?\s*[`\"']?([\w./-]+\.[\w]+)[`\"']?",
        raw,
        re.I,
    )
    save_under = re.search(
        r"(?:under|to|into|as)\s+[`\"']?([\w./-]+\.[\w]+)[`\"']?",
        raw,
        re.I,
    )
    if write_m or (save_under and re.search(r"\b(?:create|write|save|make)\b", lower)):
        # Task agent owns multi-step create; only auto-tool when content is explicit
        content_m = re.search(
            r"(?:with\s+content|containing|that\s+says)\s+[\"'](.+?)[\"']\s*$",
            raw,
            re.I,
        )
        if content_m:
            path = (write_m or save_under).group(1)  # type: ignore[union-attr]
            return ToolCall(
                "fs.write",
                {"path": _resolve_path(path), "text": content_m.group(1) + "\n"},
                confidence=0.9,
                source="rules",
            )

    # fs.read
    read_m = re.search(
        r"\b(?:read|cat|show|open)\s+(?:file\s+)?[`\"']?([^\s`\"']+)[`\"']?",
        raw,
        re.I,
    )
    if read_m:
        return ToolCall(
            "fs.read",
            {"path": _resolve_path(read_m.group(1))},
            confidence=0.88,
            source="rules",
        )

    # fs.exists
    exists_m = re.search(
        r"\b(?:does|check|exists?)\s+(?:file\s+)?[`\"']?([^\s`\"']+)[`\"']?\s+exist",
        raw,
        re.I,
    )
    if not exists_m:
        exists_m = re.search(r"\bfs\.exists\s+[`\"']?([^\s`\"']+)[`\"']?", raw, re.I)
    if exists_m:
        return ToolCall(
            "fs.exists",
            {"path": _resolve_path(exists_m.group(1))},
            confidence=0.86,
            source="rules",
        )

    # folder context
    folder_m = re.search(
        r"\b(?:inspect|index)\s+(?:folder\s+)?[`\"']?([\w./-]+)[`\"']?(?:\s+folder)?",
        raw,
        re.I,
    )
    if folder_m:
        path = folder_m.group(1)
        known = {"agents", "core", "swarm", "ghost_sentinel", "mcp", "llm", "learning", "knowledge"}
        if "folder" in lower or "/" in path or path in known:
            return ToolCall(
                "fs.folder_context",
                {"path": path},
                confidence=0.84,
                source="rules",
            )

    # shell
    if re.search(r"\b(?:run\s+)?pwd\b", lower):
        return ToolCall("shell.run", {"command": "pwd"}, confidence=0.9, source="rules")
    if re.search(r"\b(?:list|ls)\s+(?:files?|dir(?:ectory)?)\b", lower):
        return ToolCall("shell.run", {"command": "ls"}, confidence=0.85, source="rules")

    # ping mcp
    if re.fullmatch(r"ping(?:\s+mcp|\s+tools?)?", lower):
        return ToolCall("ping", {}, confidence=0.95, source="rules")

    # healing list
    if re.search(r"\b(?:list|show)\s+heal(?:ing)?\s+proposals?\b", lower):
        return ToolCall("healing.list", {"limit": 5}, confidence=0.88, source="rules")

    # web search tool phrasing (decision engine handles /search separately)
    if "web" in lower or "internet" in lower:
        search_m = re.search(
            r"\b(?:search|look up|google)\s+(?:the\s+web\s+for\s+|for\s+)?(.+)",
            raw,
            re.I,
        )
        if search_m:
            q = search_m.group(1).strip().strip("?")
            if q:
                return ToolCall(
                    "web.search",
                    {"query": q, "num_results": 5},
                    confidence=0.8,
                    source="rules",
                )

    # GitHub
    gh_m = re.search(
        r"\b(?:search\s+)?github\s+(?:for\s+|repos?\s+)?(.+)",
        raw,
        re.I,
    )
    if gh_m and "readme" not in lower:
        q = gh_m.group(1).strip().strip("?")
        if q:
            return ToolCall("github.search", {"query": q, "limit": 5}, confidence=0.9, source="rules")

    gh_rm = re.search(r"\bgithub\s+readme\s+([\w.-]+)/([\w.-]+)\b", raw, re.I)
    if gh_rm:
        return ToolCall(
            "github.readme",
            {"owner": gh_rm.group(1), "repo": gh_rm.group(2)},
            confidence=0.92,
            source="rules",
        )

    # HuggingFace
    hf_m = re.search(
        r"\b(?:search\s+)?(?:huggingface|hugging\s*face|hf)\s+(?:models?\s+)?(?:for\s+)?(.+)",
        raw,
        re.I,
    )
    if hf_m and "dataset" not in lower:
        q = hf_m.group(1).strip().strip("?")
        if q:
            return ToolCall("hf.search_models", {"query": q, "limit": 5}, confidence=0.9, source="rules")

    hf_d = re.search(
        r"\b(?:search\s+)?(?:huggingface|hugging\s*face|hf)\s+datasets?\s+(?:for\s+)?(.+)",
        raw,
        re.I,
    )
    if hf_d:
        q = hf_d.group(1).strip().strip("?")
        if q:
            return ToolCall("hf.search_datasets", {"query": q, "limit": 5}, confidence=0.9, source="rules")

    return None


def validate_tool_call(call: ToolCall) -> tuple[bool, str]:
    schema = SCHEMA_BY_NAME.get(call.name)
    if not schema:
        return False, f"unknown tool: {call.name}"
    required = schema.get("parameters", {}).get("required", [])
    for key in required:
        if key not in call.arguments or call.arguments[key] in (None, ""):
            return False, f"missing required argument: {key}"
    return True, "ok"


def execute_tool(call: ToolCall) -> Dict[str, Any]:
    ok, msg = validate_tool_call(call)
    if not ok:
        return {"status": "error", "error": msg, "tool": call.name}
    from mcp.server import MCPClient
    result = MCPClient.call(call.name, call.arguments)
    if isinstance(result, dict) and result.get("error"):
        result["status"] = "error"
    else:
        result["status"] = result.get("status", "ok")
    result["tool"] = call.name
    return result


def format_tool_reply(call: ToolCall, result: Dict[str, Any]) -> str:
    if result.get("status") == "error" or result.get("error"):
        return f"Tool {call.name} failed: {result.get('error', result)}"

    name = call.name
    if name == "ping":
        return "MCP ping: pong" if result.get("pong") else str(result)

    if name == "fs.exists":
        exists = result.get("exists", False)
        path = call.arguments.get("path", "?")
        return f"{'Exists' if exists else 'Missing'}: {path}"

    if name == "fs.read":
        path = result.get("path", call.arguments.get("path", "?"))
        text = (result.get("text") or "")[:1500]
        return f"File: {path}\n\n{text}"

    if name == "github.search":
        from tools.github_api import format_search_for_chat

        return format_search_for_chat(result)

    if name == "github.readme":
        if result.get("status") == "error":
            return f"GitHub readme failed: {result.get('error')}"
        return f"README {call.arguments.get('owner')}/{call.arguments.get('repo')}:\n\n{(result.get('content') or '')[:2000]}"

    if name == "github.file":
        if result.get("error"):
            return f"GitHub file failed: {result.get('error')}"
        if result.get("type") == "dir":
            names = [e.get("name") for e in (result.get("entries") or [])]
            return "Dir entries: " + ", ".join(names[:30])
        return f"File {result.get('path')}:\n\n{(result.get('content') or '')[:2000]}"

    if name in ("hf.search_models", "hf.search_datasets"):
        from tools.huggingface_api import format_search_for_chat

        return format_search_for_chat(result)

    if name == "hf.pull_dataset":
        if result.get("status") == "error":
            return f"HF pull failed: {result.get('error')}"
        return (
            f"HF dataset pull: {result.get('dataset_id') or call.arguments.get('dataset_id')} "
            f"rows={result.get('rows', 0)} path={result.get('path') or result.get('info_path')}"
        )

    if name == "fs.folder_context":
        from knowledge.folder_index import format_folder_summary
        if result.get("status") == "ok":
            return format_folder_summary(result)
        return result.get("error", str(result))

    if name == "web.search":
        from tools.web_search import format_results_for_chat
        return format_results_for_chat(result)

    if name == "http.get":
        url = result.get("url", call.arguments.get("url", ""))
        body = (result.get("body") or "")[:1200]
        return f"Fetched {url} ({result.get('bytes', 0)} bytes)\n\n{body}"

    if name == "shell.run":
        rc = result.get("returncode", "?")
        out = (result.get("stdout") or "").strip()
        err = (result.get("stderr") or "").strip()
        lines = [f"$ {result.get('command', '')}", f"exit {rc}"]
        if out:
            lines.append(out)
        if err:
            lines.append(f"stderr: {err}")
        return "\n".join(lines)

    if name == "healing.list":
        props = result.get("proposals") or []
        if not props:
            return "No healing proposals yet."
        from learning.healing.hybrid import format_proposal_brief
        blocks = [format_proposal_brief(p) for p in props[:3]]
        return "Recent healing proposals:\n\n" + "\n---\n".join(blocks)

    return json.dumps(result, indent=2, default=str)[:2000]


def maybe_call_tools(text: str) -> Optional[Dict[str, Any]]:
    """
    Classify and return a tool call dict, or None.

    Used by Telegram pre-pass and LLMClient.
    """
    call = classify_tool(text)
    if call is None and os.getenv("PROM_LLM_TOOL_SELECT", "").lower() in ("1", "true", "yes"):
        call = _llm_select_tool(text)
    if call is None:
        return None
    ok, msg = validate_tool_call(call)
    if not ok:
        logger.info("tool call invalid: %s", msg)
        return None
    return call.to_dict()


def run_tool_from_message(text: str) -> Optional[str]:
    """Classify → execute → format. Returns reply text or None."""
    call_dict = maybe_call_tools(text)
    if not call_dict:
        return None
    call = ToolCall(
        name=call_dict["name"],
        arguments=call_dict.get("arguments") or {},
        confidence=call_dict.get("confidence", 0),
        source=call_dict.get("source", "rules"),
    )
    result = execute_tool(call)
    return format_tool_reply(call, result)


def _llm_select_tool(text: str) -> Optional[ToolCall]:
    """Optional OpenAI tools API selection when rules miss."""
    try:
        from llm.backends.registry import build_backends
        from mcp.schemas import openai_tools_payload
        import urllib.request

        backends = build_backends()
        openai = backends.get("openai")
        if not openai or not openai.available():
            return None

        body = json.dumps({
            "model": openai.model,
            "tools": openai_tools_payload(),
            "tool_choice": "auto",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Select at most one MCP tool to answer the user. "
                        "Return tool call only when clearly needed."
                    ),
                },
                {"role": "user", "content": text},
            ],
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {openai.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        msg = (payload.get("choices") or [{}])[0].get("message", {})
        tcs = msg.get("tool_calls") or []
        if not tcs:
            return None
        fn = tcs[0].get("function") or {}
        name = fn.get("name", "")
        args_raw = fn.get("arguments") or "{}"
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        if name not in SCHEMA_BY_NAME:
            return None
        return ToolCall(name, args, confidence=0.75, source="openai")
    except Exception as exc:
        logger.debug("LLM tool select failed: %s", exc)
        return None