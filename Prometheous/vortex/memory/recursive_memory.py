"""
Recursive Memory DB — hierarchical + graph memory for Neureact Vortex.

Levels: chunk → summary → meta_summary → global_insight
Edges: RECURS_TO, ENTANGLES_WITH, METAMORPHOSES_INTO, SUMMARIZES, TEMPORAL_NEXT

Inspired by SuperPrompt <recursion_engine>, MemGPT-style compression, RAPTOR trees.
Uses NetworkX (already in requirements) so it runs offline without Neo4j.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
import numpy as np


class MemoryLevel(str, Enum):
    CHUNK = "chunk"
    SUMMARY = "summary"
    META = "meta_summary"
    GLOBAL = "global_insight"
    ENTITY = "entity"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


# SuperPrompt-aligned edge types
EDGE_TYPES = (
    "RECURS_TO",
    "ENTANGLES_WITH",
    "METAMORPHOSES_INTO",
    "SUMMARIZES",
    "TEMPORAL_NEXT",
    "CAUSES",
    "RELATED",
    "GÖDEL_RELATED",
)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _hash_embed(text: str, dim: int = 128) -> np.ndarray:
    """Deterministic embedding fallback (no sentence-transformers required)."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand via repeated hashing for dim stability
    buf = bytearray(h)
    while len(buf) < dim:
        buf.extend(hashlib.sha256(bytes(buf[-32:])).digest())
    vec = np.asarray([(b / 127.5) - 1.0 for b in buf[:dim]], dtype=np.float32)
    n = np.linalg.norm(vec)
    return vec / n if n > 0 else vec


@dataclass
class MemoryNode:
    id: str
    content: str
    level: MemoryLevel
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    strength: float = 1.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["level"] = self.level.value if isinstance(self.level, MemoryLevel) else self.level
        return d


class RecursiveMemoryDB:
    """
    Hierarchical recursive memory with hybrid vector + graph retrieval.

    recursion_engine.explore(concept):
      if fundamental → analyze
      else → explore(deconstruct)  # bounded by max_depth
    """

    def __init__(self, max_depth: int = 4, sim_threshold: float = 0.72):
        self.graph = nx.DiGraph()
        self.max_depth = max_depth
        self.sim_threshold = sim_threshold
        self._embedder = None
        self._counters = {lv: 0 for lv in MemoryLevel}

    # ── embedding ──────────────────────────────────────────
    def _get_embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception:
                self._embedder = False
        return self._embedder if self._embedder is not False else None

    def embed(self, text: str) -> np.ndarray:
        emb = self._get_embedder()
        if emb is not None:
            return np.asarray(emb.encode(text), dtype=np.float32)
        return _hash_embed(text)

    def _next_id(self, level: MemoryLevel) -> str:
        self._counters[level] = self._counters.get(level, 0) + 1
        return f"{level.value}_{self._counters[level]:05d}"

    # ── write path ─────────────────────────────────────────
    def store(
        self,
        content: str,
        level: MemoryLevel | str = MemoryLevel.CHUNK,
        *,
        node_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        parent_id: Optional[str] = None,
        edge_type: str = "SUMMARIZES",
        strength: float = 1.0,
    ) -> str:
        if isinstance(level, str):
            level = MemoryLevel(level)
        nid = node_id or self._next_id(level)
        vec = self.embed(content)
        node = MemoryNode(
            id=nid,
            content=content,
            level=level,
            metadata=metadata or {},
            strength=strength,
        )
        self.graph.add_node(
            nid,
            **node.to_dict(),
            embedding=vec,
        )
        if parent_id and self.graph.has_node(parent_id):
            self.graph.add_edge(parent_id, nid, type=edge_type, weight=strength)
        return nid

    def link(
        self,
        src: str,
        dst: str,
        edge_type: str = "RECURS_TO",
        weight: float = 1.0,
        **attrs,
    ) -> None:
        if not self.graph.has_node(src) or not self.graph.has_node(dst):
            raise KeyError(f"Missing node for edge {src} → {dst}")
        if edge_type not in EDGE_TYPES:
            edge_type = "RELATED"
        self.graph.add_edge(src, dst, type=edge_type, weight=weight, **attrs)

    def store_episode(
        self,
        interaction: str,
        *,
        summary: Optional[str] = None,
        meta_summary: Optional[str] = None,
        entities: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Hierarchical write: raw → summary → meta, with recursive links.
        Returns ids for each level created.
        """
        ids: Dict[str, str] = {}
        chunk_id = self.store(interaction, MemoryLevel.CHUNK, metadata={"kind": "episode"})
        ids["chunk"] = chunk_id

        if summary:
            sum_id = self.store(
                summary,
                MemoryLevel.SUMMARY,
                metadata={"kind": "episode_summary"},
                parent_id=chunk_id,
                edge_type="SUMMARIZES",
            )
            # recursive link: summary RECURS_TO chunk (drill-down)
            self.link(sum_id, chunk_id, "RECURS_TO", weight=0.9)
            ids["summary"] = sum_id
            parent_for_meta = sum_id
        else:
            parent_for_meta = chunk_id

        if meta_summary:
            meta_id = self.store(
                meta_summary,
                MemoryLevel.META,
                metadata={"kind": "meta"},
                parent_id=parent_for_meta,
                edge_type="SUMMARIZES",
            )
            self.link(meta_id, parent_for_meta, "RECURS_TO", weight=0.85)
            ids["meta"] = meta_id

        for ent in entities or []:
            eid = self.store(
                ent,
                MemoryLevel.ENTITY,
                metadata={"kind": "entity_ref"},
            )
            self.link(chunk_id, eid, "ENTANGLES_WITH", weight=0.7)
            ids.setdefault("entities", "")
            ids["entities"] = (ids.get("entities") or "") + f"{eid},"

        return ids

    def compress_hierarchy(
        self,
        node_ids: List[str],
        *,
        level: MemoryLevel = MemoryLevel.SUMMARY,
        max_chars: int = 800,
    ) -> str:
        """Simple extractive compressor for hierarchical summarization training."""
        parts = []
        for nid in node_ids:
            if self.graph.has_node(nid):
                parts.append(self.graph.nodes[nid].get("content", ""))
        joined = " | ".join(parts)
        if len(joined) <= max_chars:
            return joined
        # Keep head + tail signal
        half = max_chars // 2 - 10
        return joined[:half] + " … " + joined[-half:]

    # ── retrieval ──────────────────────────────────────────
    def vector_search(self, query: str, top_k: int = 5) -> List[Tuple[str, float, dict]]:
        q = self.embed(query)
        scored: List[Tuple[str, float, dict]] = []
        for nid, data in self.graph.nodes(data=True):
            emb = data.get("embedding")
            if emb is None:
                continue
            sim = _cosine(q, np.asarray(emb, dtype=np.float32))
            scored.append((nid, sim, data))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def recursive_search(
        self,
        query: str,
        *,
        top_k: int = 5,
        max_depth: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        SuperPrompt-style recursion_engine over memory graph:
          1) vector seed hits
          2) recursive RECURS_TO / SUMMARIZES traversal
          3) compress path into context block
        """
        depth_limit = max_depth if max_depth is not None else self.max_depth
        seeds = self.vector_search(query, top_k=top_k)
        paths: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for nid, score, data in seeds:
            path = self._explore(nid, depth=0, max_depth=depth_limit, seen=seen)
            paths.append(
                {
                    "seed": nid,
                    "score": score,
                    "level": data.get("level"),
                    "content": data.get("content", "")[:400],
                    "traversal": path,
                }
            )

        flat_contents = []
        for p in paths:
            flat_contents.append(p["content"])
            for step in p["traversal"]:
                flat_contents.append(step.get("content", ""))

        summary = self.compress_hierarchy(
            [p["seed"] for p in paths] + [s["id"] for p in paths for s in p["traversal"]],
            level=MemoryLevel.META,
        )

        return {
            "query": query,
            "max_depth": depth_limit,
            "seeds": len(seeds),
            "paths": paths,
            "compressed_context": summary,
            "operator": "recursion_engine.explore",
        }

    def _explore(
        self,
        node_id: str,
        depth: int,
        max_depth: int,
        seen: set[str],
    ) -> List[dict]:
        if depth >= max_depth or node_id in seen or not self.graph.has_node(node_id):
            return []
        seen.add(node_id)
        out: List[dict] = []
        # Prefer recursive drill-down edges
        for _, dst, edata in self.graph.out_edges(node_id, data=True):
            et = edata.get("type", "RELATED")
            if et not in ("RECURS_TO", "SUMMARIZES", "METAMORPHOSES_INTO", "ENTANGLES_WITH"):
                continue
            nd = self.graph.nodes[dst]
            step = {
                "id": dst,
                "edge": et,
                "depth": depth + 1,
                "level": nd.get("level"),
                "content": (nd.get("content") or "")[:300],
                "operator": "♢" if et == "RECURS_TO" else ("⍟" if et == "METAMORPHOSES_INTO" else "∝"),
            }
            out.append(step)
            out.extend(self._explore(dst, depth + 1, max_depth, seen))
        return out

    def context_block(self, query: str, max_tokens: int = 1200) -> str:
        result = self.recursive_search(query)
        text = result["compressed_context"]
        # rough char budget
        budget = max_tokens * 4
        return text[:budget]

    # ── persistence ────────────────────────────────────────
    def dump(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        nodes = []
        for nid, data in self.graph.nodes(data=True):
            row = {k: v for k, v in data.items() if k != "embedding"}
            row["id"] = nid
            nodes.append(row)
        edges = [
            {"src": u, "dst": v, **{k: val for k, val in d.items()}}
            for u, v, d in self.graph.edges(data=True)
        ]
        payload = {
            "version": 1,
            "max_depth": self.max_depth,
            "counters": {k.value if isinstance(k, MemoryLevel) else k: v for k, v in self._counters.items()},
            "nodes": nodes,
            "edges": edges,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self, path: str | Path) -> None:
        path = Path(path)
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.graph.clear()
        self.max_depth = int(payload.get("max_depth", self.max_depth))
        for k, v in (payload.get("counters") or {}).items():
            try:
                self._counters[MemoryLevel(k)] = int(v)
            except ValueError:
                pass
        for n in payload.get("nodes", []):
            nid = n.pop("id")
            content = n.get("content", "")
            n["embedding"] = self.embed(content)
            if "level" in n and not isinstance(n["level"], MemoryLevel):
                try:
                    n["level"] = MemoryLevel(n["level"]).value
                except ValueError:
                    pass
            self.graph.add_node(nid, **n)
        for e in payload.get("edges", []):
            self.graph.add_edge(e["src"], e["dst"], **{k: v for k, v in e.items() if k not in ("src", "dst")})

    def stats(self) -> dict:
        levels: Dict[str, int] = {}
        for _, data in self.graph.nodes(data=True):
            lv = data.get("level", "unknown")
            levels[str(lv)] = levels.get(str(lv), 0) + 1
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "levels": levels,
            "max_depth": self.max_depth,
        }
