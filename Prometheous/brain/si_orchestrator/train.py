#!/usr/bin/env python3
"""CLI: python -m si_orchestrator.train --epochs 5"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# package root = brain/
_BRAIN = Path(__file__).resolve().parents[1]
if str(_BRAIN) not in sys.path:
    sys.path.insert(0, str(_BRAIN))

from si_orchestrator.learning.trainer import train
from si_orchestrator.learning.tuning_state import load_tuning


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Train/tune Prometheous SI")
    p.add_argument("--epochs", type=int, default=5, help="Tuning epochs (default 5)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="si_orchestrator package dir",
    )
    p.add_argument("--no-persist", action="store_true", help="Do not write tuning.json")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--show-tuning", action="store_true", help="Print current tuning and exit")
    args = p.parse_args(argv)

    if args.show_tuning:
        t = load_tuning(args.base_dir / "data" / "tuning.json")
        print(json.dumps(t.to_dict(), indent=2))
        return 0

    report = train(
        epochs=args.epochs,
        base_dir=args.base_dir,
        seed=args.seed,
        persist=not args.no_persist,
        verbose=not args.quiet,
    )
    if args.quiet:
        print(json.dumps(report.to_dict(), indent=2, default=str)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
