"""
Vortex GraphRAG index — NetworkX hybrid store with SuperPrompt extraction.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import networkx as nx
import numpy as np

from vortex.indexing.extract import GraphExtractor, ExtractionResult
from vortex.memory.recursive_memory import RecursiveMemoryDB, MemoryLevel, _cosine


class VortexGraphIndex:
    """
    GraphRAG indexing layer:
      text chunks → SuperPrompt-guided extraction → entity/relation graph
      + recursive memory hierarchy for long context.
    """

    def __init__(
        self,
        extractor: Optional[GraphExtractor] = None,
        memory: Optional[RecursiveMemoryDB] = None,
        chunk_size: int = 600,
        sim_threshold: float = 0.78,
    ):
        self.extractor = extractor or GraphExtractor()
        self.memory = memory or RecursiveMemoryDB()
        self.graph = nx.DiGraph()
        self.chunk_size = chunk_size
        self.sim_threshold = sim_threshold
        self._chunk_count = 0

    def _embed(self, text: str) -> np.ndarray:
        return self.memory.embed(text)

    def add_document(self, text: str, source: str = "doc") -> Dict[str, Any]:
        """Chunk, extract, index, and store hierarchical memory."""
        chunks = self._chunk(text)
        stats = {"chunks": 0, "entities": 0, "relations": 0, "extractions": []}

        for i, chunk in enumerate(chunks):
            self._chunk_count += 1
            cid = f"{source}#c{i}"
            emb = self._embed(chunk)
            self.graph.add_node(
                cid,
                content=chunk,
                node_type="CHUNK",
                source=source,
                embedding=emb,
            )
            # hierarchical memory
            summary = chunk[:180] + ("…" if len(chunk) > 180 else "")
            self.memory.store_episode(chunk, summary=summary)

            result = self.extractor.extract(chunk)
            stats["extractions"].append(result.to_dict())
            stats["chunks"] += 1
            self._merge_extraction(result, chunk_id=cid, source=source)
            stats["entities"] += len(result.entities)
            stats["relations"] += len(result.relations)

        self._link_similar_chunks()
        return stats

    def _chunk(self, text: str) -> List[str]:
        text = text.strip()
        if not text:
            return []
        if len(text) <= self.chunk_size:
            return [text]
        out = []
        for i in range(0, len(text), self.chunk_size):
            piece = text[i : i + self.chunk_size].strip()
            if piece:
                out.append(piece)
        return out

    def _merge_extraction(self, result: ExtractionResult, chunk_id: str, source: str) -> None:
        for ent in result.entities:
            eid = f"{source}::{ent.id}"
            if not self.graph.has_node(eid):
                self.graph.add_node(
                    eid,
                    content=ent.name,
                    node_type="ENTITY",
                    entity_type=ent.type,
                    source=source,
                    embedding=self._embed(ent.name),
                )
                self.memory.store(
                    ent.name,
                    MemoryLevel.ENTITY,
                    node_id=f"mem_{eid}",
                    metadata={"entity_type": ent.type, "source": source},
                )
            self.graph.add_edge(chunk_id, eid, type="MENTIONS", weight=1.0)

        for rel in result.relations:
            src = f"{source}::{rel.source}"
            dst = f"{source}::{rel.target}"
            if self.graph.has_node(src) and self.graph.has_node(dst):
                self.graph.add_edge(src, dst, type=rel.type, weight=1.0, evidence=rel.evidence)
                mem_src, mem_dst = f"mem_{src}", f"mem_{dst}"
                if self.memory.graph.has_node(mem_src) and self.memory.graph.has_node(mem_dst):
                    et = {
                        "RELATED": "ENTANGLES_WITH",
                        "EVOLVES_INTO": "METAMORPHOSES_INTO",
                        "CAUSES": "CAUSES",
                    }.get(rel.type, "RELATED")
                    try:
                        self.memory.link(mem_src, mem_dst, edge_type=et)
                    except KeyError:
                        pass

        for link in result.recursive_links:
            src = f"{source}::{link.get('from')}"
            dst = f"{source}::{link.get('to')}"
            if self.graph.has_node(src) and self.graph.has_node(dst):
                self.graph.add_edge(
                    src,
                    dst,
                    type="RECURS_TO",
                    weight=float(link.get("depth_hint", 1)),
                    operator=link.get("operator", "explore"),
                )

    def _link_similar_chunks(self) -> None:
        chunks = [
            (n, d)
            for n, d in self.graph.nodes(data=True)
            if d.get("node_type") == "CHUNK" and "embedding" in d
        ]
        for i, (ni, di) in enumerate(chunks):
            vi = np.asarray(di["embedding"], dtype=np.float32)
            for nj, dj in chunks[i + 1 :]:
                vj = np.asarray(dj["embedding"], dtype=np.float32)
                sim = _cosine(vi, vj)
                if sim >= self.sim_threshold:
                    self.graph.add_edge(ni, nj, type="SIMILAR", weight=sim)
                    self.graph.add_edge(nj, ni, type="SIMILAR", weight=sim)

    def query(
        self,
        query: str,
        top_k: int = 5,
        hops: int = 2,
    ) -> List[Tuple[str, float, dict]]:
        """Hybrid vector seed + multi-hop expansion."""
        q = self._embed(query)
        scored: List[Tuple[str, float, dict]] = []
        for nid, data in self.graph.nodes(data=True):
            emb = data.get("embedding")
            if emb is None:
                continue
            sim = _cosine(q, np.asarray(emb, dtype=np.float32))
            scored.append((nid, sim, data))
        scored.sort(key=lambda x: x[1], reverse=True)
        seeds = scored[:top_k]

        expanded: Dict[str, Tuple[float, dict]] = {
            nid: (score, data) for nid, score, data in seeds
        }
        frontier = [nid for nid, _, _ in seeds]
        for _ in range(hops):
            nxt = []
            for nid in frontier:
                for _, dst, edata in self.graph.out_edges(nid, data=True):
                    if dst in expanded:
                        continue
                    nd = self.graph.nodes[dst]
                    # inherit attenuated score
                    base = expanded[nid][0] * float(edata.get("weight", 0.8)) * 0.85
                    expanded[dst] = (base, nd)
                    nxt.append(dst)
            frontier = nxt

        results = sorted(
            ((nid, sc, d) for nid, (sc, d) in expanded.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        return results[: top_k * 2]

    def query_context(self, query: str, max_tokens: int = 1500) -> str:
        hits = self.query(query, top_k=5, hops=2)
        mem = self.memory.context_block(query, max_tokens=max_tokens // 2)
        parts = [f"[memory] {mem}"]
        budget = max_tokens * 4
        used = len(parts[0])
        for nid, score, data in hits:
            line = f"[{data.get('node_type', '?')} {score:.2f}] {data.get('content', '')[:300]}"
            if used + len(line) > budget:
                break
            parts.append(line)
            used += len(line)
        return "\n".join(parts)

    def add_node(
        self,
        label: str,
        content: str,
        node_type: str = "NOTE",
        metadata: Optional[dict] = None,
    ) -> str:
        nid = f"{node_type.lower()}_{self.graph.number_of_nodes()+1}"
        self.graph.add_node(
            nid,
            content=content,
            label=label,
            node_type=node_type,
            metadata=metadata or {},
            embedding=self._embed(f"{label}\n{content}"),
        )
        return nid

    def add_edge(self, src: str, dst: str, edge_type: str = "RELATED", **attrs) -> None:
        if self.graph.has_node(src) and self.graph.has_node(dst):
            self.graph.add_edge(src, dst, type=edge_type, **attrs)

    def dump(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        nodes = []
        for nid, data in self.graph.nodes(data=True):
            row = {k: v for k, v in data.items() if k != "embedding"}
            row["id"] = nid
            nodes.append(row)
        edges = [
            {"src": u, "dst": v, **d}
            for u, v, d in self.graph.edges(data=True)
        ]
        path.write_text(
            json.dumps({"nodes": nodes, "edges": edges}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.memory.dump(path.with_suffix(".memory.json"))

    def load(self, path: str | Path) -> None:
        path = Path(path)
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.graph.clear()
        for n in payload.get("nodes", []):
            nid = n.pop("id")
            content = n.get("content", "")
            n["embedding"] = self._embed(content)
            self.graph.add_node(nid, **n)
        for e in payload.get("edges", []):
            self.graph.add_edge(
                e["src"], e["dst"], **{k: v for k, v in e.items() if k not in ("src", "dst")}
            )
        mem_path = path.with_suffix(".memory.json")
        if mem_path.exists():
            self.memory.load(mem_path)

    def stats(self) -> dict:
        types: Dict[str, int] = {}
        for _, d in self.graph.nodes(data=True):
            t = d.get("node_type", "?")
            types[t] = types.get(t, 0) + 1
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "types": types,
            "memory": self.memory.stats(),
        }
