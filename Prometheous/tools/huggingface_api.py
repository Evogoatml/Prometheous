"""
Hugging Face Hub API — search models/datasets, fetch cards, sample datasets.

Env:
  HF_TOKEN or HUGGING_FACE_HUB_TOKEN
  HF_API  — default https://huggingface.co/api
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.config import cfg

    DATA = cfg.DATA_DIR
except Exception:
    DATA = Path(__file__).resolve().parents[1] / "data"

CACHE_DIR = DATA / "external" / "huggingface"


def _headers() -> Dict[str, str]:
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN") or ""
    h = {"User-Agent": "Prometheous-Bot/1.0", "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def configured() -> bool:
    return bool(os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"))


def _get(url: str) -> Any:
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HF API {e.code}: {body}") from e


def search_models(query: str, limit: int = 5) -> Dict[str, Any]:
    base = os.getenv("HF_API", "https://huggingface.co/api").rstrip("/")
    qs = urllib.parse.urlencode({"search": query, "limit": min(limit, 20), "sort": "downloads", "direction": "-1"})
    data = _get(f"{base}/models?{qs}")
    items = []
    for m in (data if isinstance(data, list) else [])[:limit]:
        items.append(
            {
                "id": m.get("id") or m.get("modelId"),
                "pipeline_tag": m.get("pipeline_tag"),
                "downloads": m.get("downloads"),
                "likes": m.get("likes"),
                "tags": (m.get("tags") or [])[:8],
                "url": f"https://huggingface.co/{m.get('id') or m.get('modelId')}",
            }
        )
    return {"status": "ok", "query": query, "kind": "models", "results": items, "authenticated": configured()}


def search_datasets(query: str, limit: int = 5) -> Dict[str, Any]:
    base = os.getenv("HF_API", "https://huggingface.co/api").rstrip("/")
    qs = urllib.parse.urlencode({"search": query, "limit": min(limit, 20)})
    data = _get(f"{base}/datasets?{qs}")
    items = []
    for d in (data if isinstance(data, list) else [])[:limit]:
        items.append(
            {
                "id": d.get("id"),
                "downloads": d.get("downloads"),
                "likes": d.get("likes"),
                "tags": (d.get("tags") or [])[:8],
                "url": f"https://huggingface.co/datasets/{d.get('id')}",
            }
        )
    return {"status": "ok", "query": query, "kind": "datasets", "results": items, "authenticated": configured()}


def model_info(model_id: str) -> Dict[str, Any]:
    base = os.getenv("HF_API", "https://huggingface.co/api").rstrip("/")
    data = _get(f"{base}/models/{model_id}")
    return {
        "status": "ok",
        "id": data.get("id") or model_id,
        "pipeline_tag": data.get("pipeline_tag"),
        "tags": data.get("tags") or [],
        "siblings": [s.get("rfilename") for s in (data.get("siblings") or [])[:20]],
        "cardData": data.get("cardData") or {},
        "url": f"https://huggingface.co/{model_id}",
    }


def dataset_info(dataset_id: str) -> Dict[str, Any]:
    base = os.getenv("HF_API", "https://huggingface.co/api").rstrip("/")
    data = _get(f"{base}/datasets/{dataset_id}")
    return {
        "status": "ok",
        "id": data.get("id") or dataset_id,
        "tags": data.get("tags") or [],
        "cardData": data.get("cardData") or {},
        "url": f"https://huggingface.co/datasets/{dataset_id}",
    }


def pull_dataset_rows(dataset_id: str, split: str = "train", max_rows: int = 50) -> Dict[str, Any]:
    """
    Stream a small slice via datasets library if installed; else save API metadata only.
    Writes JSONL under data/external/huggingface/
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"{dataset_id.replace('/', '__')}__{split}.jsonl"
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")

    try:
        from datasets import load_dataset
    except ImportError:
        # metadata-only fallback
        info = dataset_info(dataset_id)
        meta_path = CACHE_DIR / f"{dataset_id.replace('/', '__')}__info.json"
        meta_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
        return {
            "status": "ok",
            "mode": "metadata_only",
            "hint": "pip install datasets for row pull",
            "info_path": str(meta_path),
            "info": info,
        }

    try:
        ds = load_dataset(dataset_id, split=split, streaming=True, token=token)
    except Exception as e:
        return {"status": "error", "error": str(e)}

    rows = []
    with open(out_path, "w", encoding="utf-8") as f:
        for i, row in enumerate(ds):
            if i >= max_rows:
                break
            # make json-safe
            safe = {}
            for k, v in dict(row).items():
                try:
                    json.dumps(v)
                    safe[k] = v
                except TypeError:
                    safe[k] = str(v)[:500]
            f.write(json.dumps(safe, ensure_ascii=False) + "\n")
            rows.append(safe)

    return {
        "status": "ok",
        "mode": "rows",
        "dataset_id": dataset_id,
        "split": split,
        "rows": len(rows),
        "path": str(out_path),
        "sample_keys": list(rows[0].keys()) if rows else [],
    }


def format_search_for_chat(result: Dict[str, Any]) -> str:
    if result.get("status") == "error":
        return f"HuggingFace error: {result.get('error')}"
    kind = result.get("kind", "results")
    lines = [f"🤗 HF {kind}: {result.get('query')}"]
    if not result.get("authenticated"):
        lines.append("(no HF_TOKEN — public search still works; private/gated needs token)")
    for i, r in enumerate(result.get("results") or [], 1):
        lines.append(
            f"{i}. {r.get('id')}  ↓{r.get('downloads', '?')}  "
            f"{r.get('pipeline_tag') or ''}  {r.get('url')}"
        )
    return "\n".join(lines)
