"""
Integration self-check — exercises the real decision → dispatch path.

Run standalone:
    python -m agents.integration_test

Also imported by main.py so the module is loaded at boot. It performs no
side effects on import; only the `main()` / `run_integration()` calls do.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def run_integration() -> Dict[str, Any]:
    """Route a scan intent through the real decision engine + orchestrator."""
    try:
        from core.decision import DecisionEngine
        from core.orchestrator import orchestrator
    except Exception as exc:
        return {"status": "failed", "step": "import", "error": str(exc)}

    # Standalone runs have no agents registered yet; wire the real scanner so
    # the dispatch path is exercised end to end.
    if not orchestrator.list_agents():
        try:
            from swarm.nodes import ScannerNode
            orchestrator.register_agent("scanner", ScannerNode())
        except Exception as exc:
            return {"status": "failed", "step": "agent_register", "error": str(exc)}

    engine = DecisionEngine()
    try:
        decision = engine.decide("scan localhost")
    except Exception as exc:
        return {"status": "failed", "step": "decision", "error": str(exc)}

    task = orchestrator.dispatch(decision, {"target": "localhost"})
    return {
        "status": task.status,
        "intent": decision.action,
        "agent": task.agent,
        "error": task.error,
        "result": task.result if isinstance(task.result, dict) else {"result": str(task.result)},
    }


def check_registered_agents() -> List[str]:
    try:
        from core.orchestrator import orchestrator
        return orchestrator.list_agents()
    except Exception as exc:
        return [f"registry unavailable: {exc}"]


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    print("registered agents:", ", ".join(sorted(check_registered_agents())))
    result = run_integration()
    print("integration:", result)
    return 0 if result.get("status") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
