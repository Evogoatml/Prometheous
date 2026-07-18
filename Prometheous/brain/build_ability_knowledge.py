#!/usr/bin/env python3
"""
OFFLINE builder: knowledge/training → brain knowledge index.

Not part of the bot. Run manually when you want to refresh brain memory:

    python -m brain.build_ability_knowledge

Writes:
    data/learning/ability_index.jsonl
    data/learning/ability_index_meta.json

The bot/runtime only reads those files via brain.knowledge_store.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TRAINING = ROOT / "knowledge" / "training"
DATA = ROOT / "data"
INDEX_PATH = DATA / "learning" / "ability_index.jsonl"
META_PATH = DATA / "learning" / "ability_index_meta.json"

INCLUDE_DIR_NAMES: Set[str] = {
    "algorithms",
    "_algorithms_ml",
    "machine_learning",
    "neural_network",
    "neural_networks",
    "ciphers",
    "hashes",
    "_crypto_algorithms_collection",
    "encryption_languages",
    "maths",
    "linear_algebra",
    "linear_programming",
    "matrix",
    "geometry",
    "geodesy",
    "physics",
    "data_structures",
    "graphs",
    "searches",
    "sorts",
    "dynamic_programming",
    "divide_and_conquer",
    "backtracking",
    "greedy_methods",
    "knapsack",
    "scheduling",
    "networking_flow",
    "network_dismantling",
    "boolean_algebra",
    "conversions",
    "computer_vision",
    "digital_image_processing",
    "audio_filters",
    "data_compression",
    "genetic_algorithm",
    "fuzzy_logic",
    "cellular_automata",
    "fractals",
    "quantum",
    "financial",
    "electronics",
    "blockchain",
    "cognitive_memory",
    "multi-agent-researcher",
    "Data-Mining-Algorithms",
    "strings",
    "other",
}

INCLUDE_FILE_GLOBS = ("algorithms_reference.json", "data_structures_guide.json")

# Trivia / non-skill — never into brain
EXCLUDE_PATH_PARTS: Tuple[str, ...] = (
    "/datasets/",
    "/notebook/",
    "/cpython/",
    "/suite/",
    "/framework/",
    "/.git/",
    "/venv/",
    "/__pycache__/",
    "covid",
    "billionaire",
    "anime",
    "amongus",
    "discord",
    "spotify",
    "instagram",
    "typemaster",
    "wordcloud",
    "habit_tracker",
    "expense_tracker",
    "project_euler",
    "lightly-master",
    "local-file-organizer",
)

EXCLUDE_NAME_RE = re.compile(
    r"(covid|billionaire|anime|amongus|scrap(e|er)|instagram|spotify)",
    re.I,
)

EXT_OK = {".py", ".md", ".json", ".txt"}
MAX_FILE_BYTES = 120_000
MAX_SNIPPET = 900
MAX_FILES = 8000


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except Exception:
        return str(path)


def _domain(rel: str) -> str:
    for p in Path(rel).parts:
        if p in INCLUDE_DIR_NAMES:
            return p
    return "general"


def _skip(path: Path) -> bool:
    s = str(path).replace("\\", "/").lower()
    name = path.name.lower()
    if path.suffix.lower() not in EXT_OK:
        return True
    if name.endswith(".broken.txt") or name.endswith(".disabled"):
        return True
    if name in ("agent.md", "code_of_conduct.md", "contributing.md"):
        return True
    if EXCLUDE_NAME_RE.search(name):
        return True
    for part in EXCLUDE_PATH_PARTS:
        if part in s:
            return True
    if path.name in INCLUDE_FILE_GLOBS:
        return False
    try:
        rel = path.resolve().relative_to(TRAINING.resolve())
    except Exception:
        return True
    if set(rel.parts) & INCLUDE_DIR_NAMES:
        return False
    if len(rel.parts) == 1 and (
        path.name in INCLUDE_FILE_GLOBS
        or path.name.endswith("_guide.json")
        or "reference" in path.name
    ):
        return False
    return True


def _snippet(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(raw) > MAX_FILE_BYTES:
        raw = raw[:MAX_FILE_BYTES]
    m = re.search(r'^"""([\s\S]*?)"""', raw) or re.search(r"^'''([\s\S]*?)'''", raw)
    if m and len(m.group(1).strip()) > 40:
        return m.group(1).strip()[:MAX_SNIPPET]
    lines = []
    for line in raw.splitlines():
        t = line.strip()
        if not t or t.startswith("#!") or t.startswith("from __future__"):
            continue
        if t.startswith("import ") or t.startswith("from "):
            continue
        lines.append(line)
        if sum(len(x) for x in lines) > MAX_SNIPPET:
            break
    return ("\n".join(lines) or raw)[:MAX_SNIPPET]


def _keywords(path: Path, snippet: str, domain: str) -> List[str]:
    stem = re.sub(r"[_\-.]+", " ", path.stem).lower()
    words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", stem + " " + snippet[:400].lower()))
    stop = {
        "the", "and", "for", "with", "this", "that", "from", "import", "return",
        "def", "class", "self", "none", "true", "false",
    }
    kws = [w for w in words if w not in stop][:24]
    kws += [domain, path.stem.lower()]
    return sorted(set(kws))


def build() -> Dict[str, Any]:
    if not TRAINING.is_dir():
        raise SystemExit(f"Training corpus missing: {TRAINING}")

    t0 = time.time()
    docs: List[Dict[str, Any]] = []

    for name in INCLUDE_FILE_GLOBS:
        p = TRAINING / name
        if p.is_file():
            snip = _snippet(p)
            docs.append(
                {
                    "path": _rel(p),
                    "title": p.stem,
                    "domain": "reference",
                    "snippet": snip,
                    "keywords": _keywords(p, snip, "reference"),
                    "size": p.stat().st_size,
                }
            )

    count = 0
    for dirpath, dirnames, filenames in os.walk(TRAINING):
        pruned = []
        for d in list(dirnames):
            full = str(Path(dirpath) / d).replace("\\", "/").lower()
            if any(
                x in full
                for x in (
                    "/datasets",
                    "/notebook",
                    "/cpython",
                    "/suite",
                    "/framework",
                    "/.git",
                    "/venv",
                    "/__pycache__",
                    "project_euler",
                )
            ):
                continue
            pruned.append(d)
        dirnames[:] = pruned

        for fn in filenames:
            path = Path(dirpath) / fn
            if _skip(path):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size < 40 or size > MAX_FILE_BYTES * 2:
                continue
            rel = _rel(path)
            domain = _domain(rel)
            snip = _snippet(path)
            if len(snip.strip()) < 20:
                continue
            docs.append(
                {
                    "path": rel,
                    "title": path.stem.replace("_", " "),
                    "domain": domain,
                    "snippet": snip,
                    "keywords": _keywords(path, snip, domain),
                    "size": size,
                }
            )
            count += 1
            if count >= MAX_FILES:
                break
        if count >= MAX_FILES:
            break

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    domains: Dict[str, int] = {}
    for d in docs:
        domains[d["domain"]] = domains.get(d["domain"], 0) + 1

    meta = {
        "built_at": time.time(),
        "count": len(docs),
        "domains": dict(sorted(domains.items(), key=lambda x: -x[1])),
        "training_corpus": str(TRAINING),
        "index_path": str(INDEX_PATH),
        "excludes": "covid/trivia/datasets/notebook/cpython/toys",
        "includes": "algorithms/ciphers/maths/data_structures/ml",
        "seconds": round(time.time() - t0, 2),
        "note": "Offline brain build only — training folder is not part of the bot",
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    meta = build()
    print("Brain knowledge built (offline).")
    print(f"  docs:     {meta['count']}")
    print(f"  index:    {meta['index_path']}")
    print(f"  corpus:   {meta['training_corpus']}  (NOT loaded by bot)")
    print(f"  seconds:  {meta['seconds']}")
    print(f"  domains:  {list(meta['domains'].items())[:8]}...")


if __name__ == "__main__":
    main()
