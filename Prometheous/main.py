#!/usr/bin/env python3
"""
Prometheous — single-LLM gateway.

One LLM, used ONLY to phrase natural-language replies to the user.
All decisions are rule-based. The LLM never decides or acts on its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make project root importable when run from anywhere.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.decision import engine as decision_engine
from core.orchestrator import orchestrator
from llm.client import llm
from swarm.nodes import DEFAULT_NODES

# Lightweight app-layer agents (always loaded when main.py runs).
from agents.scanner import ScannerAgent
from agents.recon import ReconAgent
from agents.exfil import ExfilAgent


def bootstrap() -> None:
    """Register default agents with the orchestrators."""
    # Register swarm built-ins
    for node_cls in DEFAULT_NODES:
        orchestrator.register_agent(node_cls.name, node_cls())

    # Register lightweight agents that ship with the project
    for cls in (ScannerAgent, ReconAgent, ExfilAgent):
        orchestrator.register_agent(cls.name, cls())


def handle(text: str) -> str:
    """Process a user message and return a phrased reply."""
    text = text.strip()
    if not text:
        return ""

    decision = decision_engine.decide(text, context={"target": text})

    if decision.action in ("dispatch", "create_skill", "run_skill", "reflect"):
        task = orchestrator.dispatch(decision, payload={"user_msg": text})
        payload = task.result or {
            "status": task.status,
            "task_id": task.task_id,
            "error": task.error,
        }
        return llm.respond(payload, text)

    # respond / greet / chat
    payload = {
        "status": "ok",
        "intent": decision.action,
        "confidence": decision.confidence,
        "reason": decision.reason,
    }
    if decision.action == "greet":
        payload["message"] = "System online. Send a request."
    else:
        payload["message"] = text

    return llm.respond(payload, text)


def repl() -> None:
    bootstrap()
    print("Prometheous ready — type 'exit' to quit.")
    print("Agents:", ", ".join(orchestrator.list_agents()))
    while True:
        try:
            text = input("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        low = text.strip().lower()
        if low in ("exit", "quit"):
            break
        if not text.strip():
            continue

        try:
            reply = handle(text)
        except Exception as exc:  # pragma: no cover
            reply = f"Error: {exc}"

        print(f"\nbot> {reply}")


if __name__ == "__main__":
    repl()
