"""
GraphRAGEngine — adapter used by NeuroReactCognitiveEngine.

Wraps VortexGraphIndex when available, else memory.graph_rag.GraphRAGStore.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class GraphRAGEngine:
    """Unified GraphRAG interface for kernel/engine/neuro_react_engine.py."""

    def __init__(self, backend: str = "vortex"):
        self.backend = backend
        self._vortex = None
        self._legacy = None
        if backend == "vortex":
            try:
                from vortex.indexing.index_graph import VortexGraphIndex

                self._vortex = VortexGraphIndex()
            except Exception:
                self.backend = "legacy"
        if self.backend == "legacy" or self._vortex is None:
            from memory.graph_rag import GraphRAGStore

            self._legacy = GraphRAGStore()
            self.backend = "legacy"

    def add_node(
        self,
        label: str,
        content: str,
        node_type: str = "NOTE",
        metadata: Optional[dict] = None,
    ) -> str:
        if self._vortex is not None:
            return self._vortex.add_node(label, content, node_type=node_type, metadata=metadata)
        # legacy: store as chunk-like node
        import hashlib

        nid = f"{node_type}:{hashlib.sha256((label + content).encode()).hexdigest()[:10]}"
        emb = self._legacy._embed(content)
        self._legacy.graph.add_node(
            nid, content=content, label=label, node_type=node_type, embedding=emb, metadata=metadata or {}
        )
        return nid

    def add_edge(self, src: str, dst: str, edge_type: str = "RELATED", **attrs) -> None:
        if self._vortex is not None:
            self._vortex.add_edge(src, dst, edge_type, **attrs)
            return
        if self._legacy.graph.has_node(src) and self._legacy.graph.has_node(dst):
            self._legacy.graph.add_edge(src, dst, type=edge_type, **attrs)

    def query_context(self, query: str, max_tokens: int = 1500) -> str:
        if self._vortex is not None:
            return self._vortex.query_context(query, max_tokens=max_tokens)
        hits = self._legacy.query(query, top_k=5)
        parts = [c[:300] for c, _ in hits]
        return "\n".join(parts)[: max_tokens * 4]

    def query(self, query: str, top_k: int = 5) -> List:
        if self._vortex is not None:
            return self._vortex.query(query, top_k=top_k)
        return self._legacy.query(query, top_k=top_k)

    def ingest(self, text: str, source: str = "doc") -> Dict[str, Any]:
        if self._vortex is not None:
            return self._vortex.add_document(text, source=source)
        # legacy path: write temp-like via process
        return {"chunks": 0, "note": "legacy GraphRAGStore has no document ingest API"}

    def stats(self) -> dict:
        if self._vortex is not None:
            return {"backend": "vortex", **self._vortex.stats()}
        return {
            "backend": "legacy",
            "nodes": self._legacy.graph.number_of_nodes(),
            "edges": self._legacy.graph.number_of_edges(),
        }
