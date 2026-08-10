
"""
RAG — lightweight semantic retrieval over the project codebase.

Uses embeddings from:
  - OpenAI (OPENAI_API_KEY + embedding model)
  - Ollama (/api/embeddings)

Then stores vectors in a simple numpy-backed index with cosine similarity.
No external DB required.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from utils.config import cfg
except Exception:
    cfg = None

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

_EMBEDDING_CACHE: Dict[str, np.ndarray] = {}
_EMBEDDING_NEGATIVE_CACHE: Dict[str, float] = {}


def _get_embedding(text: str) -> Optional[np.ndarray]:
    provider = os.getenv("PROM_RAG_PROVIDER") or getattr(getattr(cfg, "RAG", None), "provider", None) or ""
    provider = provider.lower()
    backend = provider or ("openai" if os.getenv("OPENAI_API_KEY", "") else "ollama")
    model = os.getenv("PROM_RAG_EMBEDDING_MODEL", "text-embedding-3-small") if backend == "openai" else os.getenv(
        "PROM_RAG_OLLAMA_MODEL", "nomic-embed-text"
    )
    cache_key = f"{backend}:{model}:{hashlib.md5(text[:4000].encode()).hexdigest()}"

    cached = _EMBEDDING_CACHE.get(cache_key)
    if cached is not None:
        logger.debug("rag embed cache=hit backend=%s", backend)
        return cached
    neg_ts = _EMBEDDING_NEGATIVE_CACHE.get(cache_key)
    if neg_ts is not None and time.time() < neg_ts:
        logger.debug("rag embed negative-cache skip backend=%s", backend)
        return None
    if neg_ts is not None:
        _EMBEDDING_NEGATIVE_CACHE.pop(cache_key, None)

    if backend == "openai":
        try:
            import urllib.request
            key = os.getenv("OPENAI_API_KEY") or getattr(cfg, "OPENAI_API_KEY", "") or ""
            if not key:
                return None
            body = json.dumps({"model": model, "input": text[:4000]}).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                data=body,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            emb = payload["data"][0]["embedding"]
            vec = np.array(emb, dtype=np.float32)
            _EMBEDDING_CACHE[cache_key] = vec
            return vec
        except Exception as e:
            logger.debug("openai embedding failed: %s", e)
    else:
        try:
            import urllib.request
            url = cfg.OLLAMA_URL + "/api/embeddings"
            body = json.dumps({"model": model, "prompt": text[:4000]}).encode()
            req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            emb = payload.get("embedding") or []
            if emb:
                vec = np.array(emb, dtype=np.float32)
                _EMBEDDING_CACHE[cache_key] = vec
                return vec
        except Exception as e:
            logger.debug("ollama embedding failed: %s", e)

    _EMBEDDING_NEGATIVE_CACHE[cache_key] = time.time() + 120
    return None


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class SimpleVectorStore:
    def __init__(self) -> None:
        self._texts: List[str] = []
        self._vecs: Optional[np.ndarray] = None
        self._meta: List[Dict[str, str]] = []

    def add(self, text: str, meta: Optional[Dict[str, str]] = None) -> None:
        emb = _get_embedding(text)
        if emb is None:
            return
        self._texts.append(text)
        self._meta.append(meta or {})
        if self._vecs is None:
            self._vecs = emb.reshape(1, -1)
        else:
            self._vecs = np.concatenate([self._vecs, emb.reshape(1, -1)], axis=0)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[float, str, Dict[str, str]]]:
        if self._vecs is None or self._vecs.shape[0] == 0:
            return []
        q = _get_embedding(query)
        if q is None:
            return []
        sims = np.dot(self._vecs, q) / (np.linalg.norm(self._vecs, axis=1) * np.linalg.norm(q) + 1e-9)
        idx = np.argsort(-sims)[:top_k]
        out = []
        for i in idx:
            out.append((float(sims[i]), self._texts[i], self._meta[i]))
        return out

    def size(self) -> int:
        return len(self._texts)


_store = SimpleVectorStore()


def index_project(max_files: int = 60, max_chars: int = 1200) -> Dict[str, Any]:
    count = 0
    paths = []
    for base in [ROOT / "agents", ROOT / "core", ROOT / "swarm", ROOT / "llm", ROOT / "utils", ROOT / "mcp"]:
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            paths.append(p)
    for p in (ROOT / "main.py", ROOT / "pyproject.toml", ROOT / "requirements.txt"):
        if p.exists() and p not in paths:
            paths.append(p)

    paths = paths[:max_files]
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")[: max(1, max_chars)]
        except Exception:
            continue
        if not text.strip():
            continue
        _store.add(text, meta={"path": str(p.relative_to(ROOT)), "type": "code"})
        count += 1
    return {"indexed": count, "vectors": _store.size()}


def retrieve(query: str, top_k: int = 5) -> Dict[str, Any]:
    hits = _store.search(query, top_k=top_k)
    return {
        "query": query,
        "hits": [
            {"score": round(score, 4), "path": meta.get("path", ""), "snippet": text[:400]}
            for score, text, meta in hits
        ],
    }
