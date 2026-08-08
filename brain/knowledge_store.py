"""
Brain knowledge store — runtime memory for algorithms / ciphers / maths.

THIS IS BRAIN, NOT BOT.
- The bot does not walk knowledge/training/
- The bot only queries this store (prebuilt index under data/learning/)
- knowledge/training/ is a training corpus only; build the index offline

Build (offline, not bot startup):
    python -m brain.build_ability_knowledge
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.config import cfg

    ROOT = Path(cfg.ROOT)
    DATA = Path(cfg.DATA_DIR)
except Exception:
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"

# Brain memory on disk — product of training, not the training folder itself
INDEX_PATH = DATA / "learning" / "ability_index.jsonl"
META_PATH = DATA / "learning" / "ability_index_meta.json"


@dataclass
class KnowledgeHit:
    score: float
    path: str
    title: str
    domain: str
    snippet: str
    keywords: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "path": self.path,
            "title": self.title,
            "domain": self.domain,
            "snippet": self.snippet,
            "keywords": self.keywords,
        }


class BrainKnowledgeStore:
    """
    In-brain ability knowledge. Loads only the compiled index.
    Never opens knowledge/training/ at runtime.
    """

    def __init__(self):
        self._docs: List[Dict[str, Any]] = []
        self._loaded = False

    @property
    def online(self) -> bool:
        return INDEX_PATH.is_file()

    def load(self, *, force: bool = False) -> Dict[str, Any]:
        if self._loaded and not force and self._docs:
            return self.stats()
        self._docs = []
        if not INDEX_PATH.is_file():
            self._loaded = True
            return {
                "loaded": False,
                "count": 0,
                "reason": "no brain index — run: python -m brain.build_ability_knowledge",
                "index_path": str(INDEX_PATH),
            }
        with open(INDEX_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._docs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        self._loaded = True
        return self.stats()

    def stats(self) -> Dict[str, Any]:
        domains: Dict[str, int] = {}
        for d in self._docs:
            dom = d.get("domain") or "general"
            domains[dom] = domains.get(dom, 0) + 1
        meta = {}
        if META_PATH.is_file():
            try:
                meta = json.loads(META_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "loaded": self._loaded,
            "online": self.online,
            "count": len(self._docs),
            "domains": dict(sorted(domains.items(), key=lambda x: -x[1])),
            "index_path": str(INDEX_PATH),
            "meta": {
                k: meta.get(k)
                for k in ("built_at", "count", "seconds", "excludes", "includes")
                if k in meta
            },
            # Explicit: training folder is NOT part of the bot runtime
            "training_folder_in_runtime": False,
            "note": "brain index only — knowledge/training is offline training corpus",
        }

    def query(self, q: str, top_k: int = 8) -> List[Dict[str, Any]]:
        if not self._loaded:
            self.load()
        q = (q or "").strip().lower()
        if not q or not self._docs:
            return []
        terms = set(re.findall(r"[a-z0-9]{2,}", q))
        scored: List[tuple] = []
        for doc in self._docs:
            title = str(doc.get("title") or "")
            domain = str(doc.get("domain") or "")
            path = str(doc.get("path") or "")
            keywords = doc.get("keywords") or []
            snippet = str(doc.get("snippet") or "")
            blob = f"{title} {domain} {path} {' '.join(map(str, keywords))} {snippet[:400]}".lower()
            score = 0.0
            for t in terms:
                if t in blob:
                    score += 1.0
                if t in title.lower():
                    score += 1.5
                if t in domain:
                    score += 0.8
                if t in path.lower():
                    score += 0.5
            if any(w in q for w in ("cipher", "encrypt", "hash", "aes", "rsa")) and domain in (
                "ciphers",
                "hashes",
                "_crypto_algorithms_collection",
            ):
                score += 2.0
            if any(
                w in q
                for w in ("sort", "graph", "matrix", "algorithm", "search", "tree", "dijkstra")
            ) and domain in (
                "algorithms",
                "sorts",
                "graphs",
                "searches",
                "data_structures",
                "matrix",
                "maths",
            ):
                score += 1.0
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda x: (-x[0], str(x[1].get("path") or "")))
        hits = []
        for score, doc in scored[:top_k]:
            hits.append(
                {
                    "score": round(score, 2),
                    "path": doc.get("path"),
                    "title": doc.get("title"),
                    "domain": doc.get("domain"),
                    "snippet": (doc.get("snippet") or "")[:500],
                    "keywords": (doc.get("keywords") or [])[:12],
                }
            )
        return hits

    def format_hits(self, hits: List[Dict[str, Any]], query: str = "") -> str:
        if not self.online and not hits:
            return (
                "Brain knowledge offline (no index).\n"
                "Build once offline: python -m brain.build_ability_knowledge\n"
                "Training folder stays out of the bot."
            )
        if not hits:
            return f"No brain knowledge hits for: {query or '(empty)'}"
        lines = [
            f"🧠 Brain knowledge ({len(hits)} hits)"
            + (f" for: {query[:80]}" if query else ""),
            "",
        ]
        for h in hits:
            lines.append(f"• [{h.get('domain')}] {h.get('title')}  (score={h.get('score')})")
            lines.append(f"  {h.get('path')}")
            snip = (h.get("snippet") or "").replace("\n", " ")[:160]
            if snip:
                lines.append(f"  {snip}")
        return "\n".join(lines)


# Singleton — brain memory only
brain_knowledge = BrainKnowledgeStore()


def get_brain_knowledge() -> BrainKnowledgeStore:
    return brain_knowledge
