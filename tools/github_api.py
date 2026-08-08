"""
GitHub API client — search, read files, fetch repo context for self-growth.

Env:
  GITHUB_TOKEN or GH_TOKEN  — optional but recommended (higher rate limits)
  GITHUB_API                — default https://api.github.com
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

    ROOT = cfg.ROOT
    DATA = cfg.DATA_DIR
except Exception:
    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data"

CACHE_DIR = DATA / "external" / "github"


def _headers() -> Dict[str, str]:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or ""
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Prometheous-Bot/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(path: str, params: Optional[dict] = None) -> dict | list:
    base = os.getenv("GITHUB_API", "https://api.github.com").rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitHub API {e.code}: {body}") from e


def configured() -> bool:
    return bool(os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"))


def search_repositories(query: str, limit: int = 5) -> Dict[str, Any]:
    data = _get("search/repositories", {"q": query, "per_page": min(limit, 20), "sort": "stars"})
    items = []
    for r in (data.get("items") or [])[:limit]:
        items.append(
            {
                "full_name": r.get("full_name"),
                "description": (r.get("description") or "")[:240],
                "stars": r.get("stargazers_count"),
                "language": r.get("language"),
                "html_url": r.get("html_url"),
                "default_branch": r.get("default_branch"),
                "topics": r.get("topics") or [],
            }
        )
    return {
        "status": "ok",
        "query": query,
        "total_count": data.get("total_count", 0),
        "results": items,
        "authenticated": configured(),
    }


def search_code(query: str, limit: int = 5) -> Dict[str, Any]:
    """Code search requires auth on GitHub."""
    if not configured():
        return {
            "status": "error",
            "error": "GITHUB_TOKEN required for code search",
            "hint": "Set GITHUB_TOKEN in .env",
        }
    data = _get("search/code", {"q": query, "per_page": min(limit, 20)})
    items = []
    for r in (data.get("items") or [])[:limit]:
        items.append(
            {
                "path": r.get("path"),
                "repo": (r.get("repository") or {}).get("full_name"),
                "html_url": r.get("html_url"),
                "name": r.get("name"),
            }
        )
    return {"status": "ok", "query": query, "results": items}


def get_file(owner: str, repo: str, path: str, ref: str = "") -> Dict[str, Any]:
    params = {"ref": ref} if ref else None
    # Contents API returns base64 for files
    data = _get(f"repos/{owner}/{repo}/contents/{path.lstrip('/')}", params)
    if isinstance(data, list):
        return {
            "status": "ok",
            "type": "dir",
            "entries": [{"name": e.get("name"), "type": e.get("type"), "path": e.get("path")} for e in data[:50]],
        }
    import base64

    content = ""
    if data.get("encoding") == "base64" and data.get("content"):
        raw = data["content"].replace("\n", "")
        content = base64.b64decode(raw).decode("utf-8", errors="replace")
    return {
        "status": "ok",
        "type": "file",
        "path": data.get("path"),
        "html_url": data.get("html_url"),
        "size": data.get("size"),
        "content": content[:80_000],
        "truncated": len(content) > 80_000,
    }


def get_readme(owner: str, repo: str) -> Dict[str, Any]:
    try:
        data = _get(f"repos/{owner}/{repo}/readme")
    except RuntimeError as e:
        return {"status": "error", "error": str(e)}
    import base64

    content = ""
    if data.get("encoding") == "base64" and data.get("content"):
        content = base64.b64decode(data["content"].replace("\n", "")).decode("utf-8", errors="replace")
    return {
        "status": "ok",
        "name": data.get("name"),
        "html_url": data.get("html_url"),
        "content": content[:40_000],
    }


def save_snippet(owner: str, repo: str, path: str, content: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = f"{owner}__{repo}__{path.replace('/', '_')}"
    dest = CACHE_DIR / safe
    dest.write_text(content, encoding="utf-8")
    return dest


def format_search_for_chat(result: Dict[str, Any]) -> str:
    if result.get("status") == "error":
        return f"GitHub error: {result.get('error')}"
    lines = [f"🐙 GitHub search: {result.get('query')} ({result.get('total_count', '?')} total)"]
    if not result.get("authenticated"):
        lines.append("(unauthenticated — set GITHUB_TOKEN for higher limits / code search)")
    for i, r in enumerate(result.get("results") or [], 1):
        if "full_name" in r:
            lines.append(f"{i}. {r['full_name']} ★{r.get('stars')} — {r.get('description', '')[:100]}")
            lines.append(f"   {r.get('html_url')}")
        else:
            lines.append(f"{i}. {r.get('repo')}:{r.get('path')}")
            lines.append(f"   {r.get('html_url')}")
    return "\n".join(lines)
