"""
JSON file memory backend (Phase 1).

Extensible: implements MemoryBackend. Later swap for Rust Hopfield via same ABC.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from ..core.interfaces import MemoryBackend, MemoryRecord, RecallQuery
from ..utils.ids import new_id
from .scoring import rank_score, tokens


class JsonMemoryBackend(MemoryBackend):
    name = "json"
    version = "1.1.0"

    def __init__(self, path: str | Path = "data/memory_store.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, MemoryRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for item in raw.get("records", []):
                rec = MemoryRecord.from_dict(item)
                self._records[rec.id] = rec
        except (OSError, json.JSONDecodeError, TypeError):
            self._records = {}

    def _save(self) -> None:
        payload = {
            "schema_version": "1.0.0",
            "backend": self.name,
            "records": [r.to_dict() for r in self._records.values()],
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def store(self, record: MemoryRecord) -> str:
        if not record.id:
            record.id = new_id("mem")
        if not record.created_at:
            record.created_at = time.time()
        self._records[record.id] = record
        self._save()
        return record.id

    def recall(self, query: RecallQuery) -> List[MemoryRecord]:
        qtoks = tokens(query.text)
        scored: List[MemoryRecord] = []
        for rec in self._records.values():
            score = rank_score(
                content=rec.content,
                query_tokens=qtoks,
                tags=list(rec.tags or []),
                query_tags=list(query.tags or []),
                created_at=float(rec.created_at or 0.0),
                provenance=dict(rec.provenance or {}),
            )
            if score >= query.min_score and (score > 0.05 or not qtoks):
                out = MemoryRecord.from_dict(rec.to_dict())
                out.score = score
                out.provenance = {
                    **rec.provenance,
                    "recall_backend": self.name,
                    "recall_score": score,
                    "ranker": "recency_success_lexical_v1",
                }
                scored.append(out)
        scored.sort(key=lambda r: r.score, reverse=True)
        if not scored and self._records:
            # fallback: most recent successful, else most recent
            pool = sorted(
                self._records.values(),
                key=lambda r: (
                    1 if (r.provenance or {}).get("success") else 0,
                    r.created_at or 0,
                ),
                reverse=True,
            )[: query.top_k]
            for r in pool:
                o = MemoryRecord.from_dict(r.to_dict())
                o.score = 0.01
                o.provenance = {
                    **r.provenance,
                    "recall_backend": self.name,
                    "fallback": "recent_success",
                }
                scored.append(o)
        return scored[: query.top_k]

    def delete(self, record_id: str) -> bool:
        if record_id in self._records:
            del self._records[record_id]
            self._save()
            return True
        return False

    def consolidate(self) -> Dict[str, Any]:
        # Phase 1: drop zero-score noise if ever marked
        before = len(self._records)
        self._records = {
            k: v for k, v in self._records.items() if v.kind != "noise"
        }
        self._save()
        return {"before": before, "after": len(self._records)}

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "path": str(self.path),
            "count": len(self._records),
        }
