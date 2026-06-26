"""
GraphRAG — knowledge graph from files.
Uses NetworkX with hash-based embeddings (sentence-transformers optional).
"""
import os
import json
import hashlib
from typing import List, Tuple, Optional
import numpy as np
import networkx as nx
from prometheus.config import cfg


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class GraphRAGStore:

    def __init__(self):
        self.graph = nx.DiGraph()
        self._file_hash = {}
        self._embedder = None

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                self._embedder = None
        return self._embedder

    def _embed(self, text: str) -> np.ndarray:
        embedder = self._get_embedder()
        if embedder:
            return embedder.encode(text)
        h = hashlib.sha256(text.encode()).digest()
        vec = [(b / 127.5) - 1.0 for b in h[:128]]
        return np.asarray(vec, dtype=np.float32)

    def build_from_path(self, root: str = None):
        root_path = root or os.path.join(cfg.BASE_DIR, "..", "knowledge")
        if not os.path.exists(root_path):
            return
        for dirpath, _, files in os.walk(root_path):
            for f in files:
                if f.endswith(('.json', '.txt', '.md')):
                    self._process_file(os.path.join(dirpath, f))
        self._connect_similar_nodes()

    def _process_file(self, file_path: str):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                raw = f.read()
        except Exception:
            return
        file_hash = hashlib.sha256(raw.encode()).hexdigest()
        if self._file_hash.get(file_path) == file_hash:
            return
        self._file_hash[file_path] = file_hash

        if file_path.endswith('.json'):
            try:
                raw = json.dumps(json.loads(raw), indent=2)
            except Exception:
                pass

        chunk_size = 500
        for i in range(0, len(raw), chunk_size):
            chunk = raw[i:i + chunk_size].strip()
            if not chunk:
                continue
            embed_vec = self._embed(chunk)
            node_id = f"{file_path}#c{i}"
            self.graph.add_node(node_id, content=chunk, embedding=embed_vec, source=file_path)

    def _connect_similar_nodes(self):
        nodes = list(self.graph.nodes(data=True))
        for i, (nid_i, data_i) in enumerate(nodes):
            vec_i = np.asarray(data_i["embedding"], dtype=np.float32)
            for nid_j, data_j in nodes[i + 1:]:
                vec_j = np.asarray(data_j["embedding"], dtype=np.float32)
                sim = _cosine(vec_i, vec_j)
                if sim >= 0.78:
                    self.graph.add_edge(nid_i, nid_j, weight=sim)
                    self.graph.add_edge(nid_j, nid_i, weight=sim)

    def query(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        q_vec = self._embed(query)
        similarities = []
        for nid, data in self.graph.nodes(data=True):
            node_vec = np.asarray(data["embedding"], dtype=np.float32)
            sim = _cosine(q_vec, node_vec)
            similarities.append((data["content"], sim))
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]

    def dump(self, path: Optional[str] = None):
        path = path or os.path.join(cfg.DATA_DIR, "graph_rag_index.json")
        data = {
            "nodes": [{"id": nid, **{k: v for k, v in attrs.items() if k != "embedding"}}
                      for nid, attrs in self.graph.nodes(data=True)],
            "edges": [{"src": u, "dst": v, "weight": d.get("weight", 0.0)}
                      for u, v, d in self.graph.edges(data=True)]
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def load(self, path: Optional[str] = None):
        path = path or os.path.join(cfg.DATA_DIR, "graph_rag_index.json")
        if not os.path.exists(path):
            return
        with open(path, 'r') as f:
            data = json.load(f)
        self.graph.clear()
        for n in data.get("nodes", []):
            nid = n.pop("id")
            content = n.get("content", "")
            embed_vec = self._embed(content)
            n["embedding"] = embed_vec
            self.graph.add_node(nid, **n)
        for e in data.get("edges", []):
            self.graph.add_edge(e["src"], e["dst"], weight=e.get("weight", 0.0))