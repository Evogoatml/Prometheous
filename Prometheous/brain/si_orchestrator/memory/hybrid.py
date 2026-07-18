"""
Hybrid / dual-brain recall: durable JSON (long-term lexical) + Hopfield (associative).

Implements MemoryBackend so the orchestrator can use name="hybrid" without code changes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

from ..core.interfaces import MemoryBackend, MemoryRecord, RecallQuery
from .hopfield_py import HopfieldMemoryBackend
from .json_backend import JsonMemoryBackend


class HybridMemoryBackend(MemoryBackend):
    """
    Dual-brain memory:
      - long_term: JsonMemoryBackend (persistence, provenance archive)
      - working_associative: HopfieldMemoryBackend (fast similarity)

    store() writes both. recall() merges scores with provenance tags.
    """

    name = "hybrid"
    version = "1.0.0"

    def __init__(
        self,
        json_path: str | Path = "data/memory_store.json",
        hopfield_dim: int = 64,
        json_weight: float = 1.0,
        hopfield_weight: float = 1.2,
    ):
        self.long_term = JsonMemoryBackend(path=json_path)
        self.associative = HopfieldMemoryBackend(dim=hopfield_dim)
        self.json_weight = json_weight
        self.hopfield_weight = hopfield_weight
        # warm hopfield from existing long-term records
        for rec in self.long_term._records.values():
            self.associative.store(MemoryRecord.from_dict(rec.to_dict()))

    def store(self, record: MemoryRecord) -> str:
        rid = self.long_term.store(record)
        # keep same id in associative
        clone = MemoryRecord.from_dict(record.to_dict())
        clone.id = rid
        self.associative.store(clone)
        return rid

    def recall(self, query: RecallQuery) -> List[MemoryRecord]:
        # Fast brain
        fast = self.associative.recall(query)
        # Slow lexical / durable
        slow = self.long_term.recall(query)

        merged: Dict[str, MemoryRecord] = {}

        def absorb(items: List[MemoryRecord], weight: float, brain: str) -> None:
            for r in items:
                key = r.id
                score = float(r.score) * weight
                if key in merged:
                    prev = merged[key]
                    prev.score = max(prev.score, score) + 0.15 * min(prev.score, score)
                    prev.provenance = {
                        **prev.provenance,
                        "brains": list(
                            set(list(prev.provenance.get("brains") or []) + [brain])
                        ),
                        "hybrid_score": prev.score,
                    }
                else:
                    out = MemoryRecord.from_dict(r.to_dict())
                    out.score = score
                    out.provenance = {
                        **r.provenance,
                        "brains": [brain],
                        "hybrid_score": score,
                        "recall_backend": self.name,
                    }
                    merged[key] = out

        absorb(fast, self.hopfield_weight, "associative_hopfield")
        absorb(slow, self.json_weight, "long_term_json")

        ranked = sorted(merged.values(), key=lambda r: r.score, reverse=True)
        return ranked[: query.top_k]

    def delete(self, record_id: str) -> bool:
        a = self.long_term.delete(record_id)
        b = self.associative.delete(record_id)
        return a or b

    def consolidate(self) -> Dict:
        j = self.long_term.consolidate()
        h = self.associative.consolidate()
        return {
            "long_term": j,
            "associative": h,
            "ts": time.time(),
            "note": "Phase1 consolidate; sleep cycles in LearningCoordinator",
        }

    def stats(self) -> Dict:
        return {
            "name": self.name,
            "long_term": self.long_term.stats(),
            "associative": self.associative.stats(),
        }
