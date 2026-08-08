"""
Vector memory backend using ChromaDB for semantic retrieval.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..core.interfaces import MemoryBackend, MemoryRecord, RecallQuery


class VectorMemoryBackend(MemoryBackend):
    name = "vector"
    version = "1.0.0"

    def __init__(self, collection_name: str = "prometheous_memories"):
        self._collection_name = collection_name
        self._client = None
        self._collection = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            import chromadb
            self._client = chromadb.Client()
            self._collection = self._client.get_or_create_collection(self._collection_name)
        except Exception:
            pass

    def store(self, record: MemoryRecord) -> str:
        if self._collection is None:
            return record.id
        meta = {
            "kind": record.kind,
            "tags": ",".join(record.tags),
            "score": record.score,
        }
        if record.provenance:
            meta["provenance"] = str(record.provenance)
        self._collection.add(
            documents=[record.content],
            metadatas=[meta],
            ids=[record.id],
        )
        return record.id

    def recall(self, query: RecallQuery) -> List[MemoryRecord]:
        if self._collection is None:
            return []
        results = self._collection.query(
            query_texts=[query.text],
            n_results=query.top_k,
        )
        records: List[MemoryRecord] = []
        if results and results.get("documents"):
            for i, doc in enumerate(results["documents"][0]):
                meta = (results.get("metadatas") or [{}])[0][i] if results.get("metadatas") else {}
                rid = (results.get("ids") or [[]])[0][i] if results.get("ids") else ""
                records.append(MemoryRecord(
                    id=rid,
                    content=doc,
                    kind=meta.get("kind", "episode"),
                    tags=meta.get("tags", "").split(",") if meta.get("tags") else [],
                    score=meta.get("score", 0.5),
                ))
        return records

    def delete(self, record_id: str) -> bool:
        if self._collection is None:
            return False
        self._collection.delete(ids=[record_id])
        return True

    def stats(self) -> Dict[str, Any]:
        if self._collection is None:
            return {"name": self.name, "version": self.version, "status": "unavailable"}
        count = self._collection.count()
        return {
            "name": self.name,
            "version": self.version,
            "collection": self._collection_name,
            "record_count": count,
        }
