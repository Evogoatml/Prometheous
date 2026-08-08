"""python -m si_orchestrator — run the Synthetic Intelligence Orchestrator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m si_orchestrator` from work1 root
_WORK1 = Path(__file__).resolve().parents[1]
if str(_WORK1) not in sys.path:
    sys.path.insert(0, str(_WORK1))

from si_orchestrator.bootstrap import build_orchestrator


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Prometheous SI Orchestrator — modular synthetic intelligence"
    )
    parser.add_argument("goal", nargs="*", help="Goal text")
    parser.add_argument("--repl", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--agent", default=None, help="Force agent name")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)

    orch = build_orchestrator()

    if args.status:
        print(json.dumps(orch.status(), indent=2))
        return 0

    if args.repl or not args.goal:
        print("Prometheous SI Orchestrator · type 'quit' to exit")
        print("registry:", orch.status()["registry"])
        while True:
            try:
                line = input("si> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.lower() in {"quit", "exit", "q"}:
                break
            if line.lower() == "status":
                print(json.dumps(orch.status(), indent=2))
                continue
            result = orch.run(line, agent_name=args.agent)
            if args.json:
                print(json.dumps(result.to_dict(), indent=2, default=str)[:6000])
            else:
                print(result.output if result.success else f"FAIL: {result.error}")
                print(f"  [success={result.success} agent={result.agent}]")
        return 0

    goal = " ".join(args.goal)
    result = orch.run(goal, agent_name=args.agent)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(result.output if result.success else f"FAIL: {result.error}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
