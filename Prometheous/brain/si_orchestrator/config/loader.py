"""Load runtime configuration (JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG_PATH = Path(__file__).with_name("default.json")


def load_config(path: str | Path | None = None) -> Dict[str, Any]:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if "schema_version" not in data:
        data["schema_version"] = "1.0.0"
    return data
