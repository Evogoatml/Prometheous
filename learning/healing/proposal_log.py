"""
Persistent proposal log — JSONL under data/learning/healing/.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.config import cfg
    HEALING_DIR = cfg.DATA_DIR / "learning" / "healing"
except Exception:
    HEALING_DIR = Path(__file__).resolve().parents[2] / "data" / "learning" / "healing"

PROPOSALS_PATH = HEALING_DIR / "proposals.jsonl"
MAX_ENTRIES = 1000


class ProposalLog:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or PROPOSALS_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Dict[str, Any]) -> str:
        proposal_id = f"h-{uuid.uuid4().hex[:12]}"
        entry = {
            "id": proposal_id,
            "ts": time.time(),
            "helpful": False,
            **record,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._trim()
        return proposal_id

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out: List[Dict[str, Any]] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(out) >= limit:
                break
        return out

    def get(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        for entry in self._iter_all():
            if entry.get("id") == proposal_id:
                return entry
        return None

    def mark_applied(self, proposal_id: str, result: Dict[str, Any]) -> bool:
        entries = self._iter_all()
        updated = False
        new_lines: List[str] = []
        for entry in entries:
            if entry.get("id") == proposal_id:
                entry["applied"] = result
                entry["applied_ts"] = time.time()
                updated = True
            new_lines.append(json.dumps(entry, ensure_ascii=False))
        if updated:
            self.path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return updated

    def mark_helpful(self, proposal_id: str) -> bool:
        entries = self._iter_all()
        updated = False
        new_lines: List[str] = []
        for entry in entries:
            if entry.get("id") == proposal_id:
                entry["helpful"] = True
                entry["helpful_ts"] = time.time()
                updated = True
            new_lines.append(json.dumps(entry, ensure_ascii=False))
        if updated:
            self.path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return updated

    def count(self) -> int:
        if not self.path.exists():
            return 0
        return sum(1 for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip())

    def _iter_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _trim(self) -> None:
        entries = self._iter_all()
        if len(entries) <= MAX_ENTRIES:
            return
        kept = entries[-MAX_ENTRIES:]
        self.path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in kept) + "\n",
            encoding="utf-8",
        )