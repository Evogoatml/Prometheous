"""
Ghost Sentinel Telegram command helpers.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple


SENTINEL_HELP = """🛡 Ghost Sentinel

/sentinel — status
/sentinel sync — publish CRDT delta
/sentinel poll — ingest peer relay
/sentinel policy — publish policy CRDT
/sentinel tools — list tool templates
/sentinel tool <template> <name> — register gated tool
/sentinel ws — relay mode + connectivity

Templates: http_probe, hash_file, ping_check, crdt_search, json_parse"""


def parse_sentinel_command(text: str) -> Optional[Dict[str, Any]]:
    """Parse ``/sentinel ...`` into an agent payload."""
    raw = text.strip()
    if not raw.lower().startswith("/sentinel"):
        if raw.lower().startswith("sentinel "):
            raw = "/" + raw
        else:
            return None

    parts = raw.split()
    if len(parts) == 1:
        return {"action": "status"}

    sub = parts[1].lower()
    mapping = {
        "sync": {"action": "sync"},
        "poll": {"action": "poll"},
        "policy": {"action": "sync_policy"},
        "tools": {"action": "templates"},
        "templates": {"action": "templates"},
        "status": {"action": "status"},
        "ws": {"action": "relay_status"},
        "help": {"action": "help"},
    }
    if sub in mapping:
        return mapping[sub]

    if sub == "tool" and len(parts) >= 4:
        return {
            "action": "propose_tool",
            "template": parts[2],
            "tool_name": parts[3],
        }
    if sub == "tool":
        return {"action": "help", "error": "usage: /sentinel tool <template> <name>"}

    return {"action": "help", "error": f"unknown subcommand: {sub}"}


def format_sentinel_reply(result: Dict[str, Any]) -> str:
    action = result.get("action", "status")
    if action == "help":
        err = result.get("error")
        return f"{SENTINEL_HELP}\n\n{err}" if err else SENTINEL_HELP

    if result.get("status") == "failed":
        return f"Ghost Sentinel error: {result.get('error', 'unknown')}"

    if action == "sync":
        return f"✓ CRDT published\n`{result.get('published', '')}`"
    if action == "sync_policy":
        return f"✓ Policy published\n`{result.get('published', '')}`"
    if action == "poll":
        merged = (result.get("result") or {}).get("merged", {})
        relay = (result.get("result") or {}).get("relay", {})
        return (
            "✓ Relay poll\n"
            f"merged: crdt={merged.get('crdt', 0)} policy={merged.get('policy', 0)} "
            f"registry={merged.get('registry', 0)} failed={merged.get('failed', 0)}\n"
            f"relay: scanned={relay.get('scanned', 0)} ingested={relay.get('ingested', 0)}"
        )
    if action == "templates":
        templates = result.get("templates") or []
        return "Ghost Sentinel templates:\n" + "\n".join(f"• {t}" for t in templates)
    if action == "propose_tool":
        inner = result.get("result") or {}
        if inner.get("error"):
            return f"Tool registration failed:\n{inner['error']}"
        return (
            f"✓ Tool registered\n"
            f"name: {inner.get('name')}\n"
            f"id: {inner.get('tool_id', '')[:16]}...\n"
            f"caps: {', '.join(inner.get('capabilities', []))}"
        )
    if action == "relay_status":
        return (
            f"Relay mode: {result.get('relay_mode')}\n"
            f"WS URL: {result.get('ws_url', 'n/a')}\n"
            f"Root: {result.get('relay_root')}"
        )

    # default status
    policy = result.get("policy") or {}
    tools = result.get("registered_tools") or []
    lines = [
        "🛡 Ghost Sentinel",
        f"crypto: {result.get('crypto_backend', '?')}",
        f"security_level: {policy.get('security_level', '?')}",
        f"pause_tools: {policy.get('pause_tool_registration', False)}",
        f"tools: {', '.join(tools) if tools else '(none)'}",
        f"relay: {result.get('relay_root', '?')}",
        f"mode: {result.get('relay_mode', 'file')}",
    ]
    metrics = result.get("metrics") or {}
    if metrics:
        lines.append(
            f"merges ok={metrics.get('merges_ok', 0)} "
            f"fail={metrics.get('merges_failed', 0)}"
        )
    return "\n".join(lines)


def run_sentinel_command(
    text: str,
    executor: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Tuple[bool, str]:
    """
    Returns (handled, reply_text).
    """
    payload = parse_sentinel_command(text)
    if payload is None:
        return False, ""
    if payload.get("action") == "help" and not payload.get("error"):
        return True, SENTINEL_HELP
    result = executor(payload)
    result["action"] = payload.get("action", "status")
    return True, format_sentinel_reply(result)