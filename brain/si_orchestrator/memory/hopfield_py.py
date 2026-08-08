"""
Neuro-symbolic Hopfield-style associative memory (Python MVP).

Phase 1 stand-in for the planned Rust Hopfield core. Same MemoryBackend
interface so a PyO3 crate can replace this later without orchestrator changes.
"""

from __future__ import annotations

import hashlib
import math
import time
from typing import Dict, List, Tuple

from ..core.interfaces import MemoryBackend, MemoryRecord, RecallQuery
from ..utils.ids import new_id


def _vectorize(text: str, dim: int = 64) -> List[float]:
    """Deterministic bag-of-hashes bipolar vector in {-1, +1}^dim."""
    vec = [0.0] * dim
    for tok in text.lower().split():
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign
    # bipolar-ish normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class HopfieldMemoryBackend(MemoryBackend):
    """
    Stores patterns; recall by cosine/dot similarity (associative retrieval).
    Not a full modern Hopfield energy descent — clear upgrade path for Rust.
    """

    name = "hopfield_py"
    version = "1.0.0"

    def __init__(self, dim: int = 64):
        self.dim = dim
        self._items: Dict[str, Tuple[MemoryRecord, List[float]]] = {}

    def store(self, record: MemoryRecord) -> str:
        if not record.id:
            record.id = new_id("hop")
        if not record.created_at:
            record.created_at = time.time()
        vec = record.embedding or _vectorize(record.content, self.dim)
        record.embedding = vec
        self._items[record.id] = (record, vec)
        return record.id

    def recall(self, query: RecallQuery) -> List[MemoryRecord]:
        qv = _vectorize(query.text, self.dim)
        scored: List[MemoryRecord] = []
        for rec, vec in self._items.values():
            s = _dot(qv, vec)
            if s >= query.min_score:
                out = MemoryRecord.from_dict(rec.to_dict())
                out.score = float(s)
                out.provenance = {
                    **rec.provenance,
                    "recall_backend": self.name,
                    "similarity": float(s),
                }
                scored.append(out)
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[: query.top_k]

    def delete(self, record_id: str) -> bool:
        return self._items.pop(record_id, None) is not None

    def consolidate(self) -> Dict:
        return {"count": len(self._items), "dim": self.dim}

    def stats(self) -> Dict:
        return {"name": self.name, "count": len(self._items), "dim": self.dim}
