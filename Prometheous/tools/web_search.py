"""
Lightweight web search — DuckDuckGo HTML (no API key) or SerpAPI (optional).

Sync-only, stdlib + urllib. Used by MCP tool and web_search agent.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Any, Dict, List, Optional

USER_AGENT = "Prometheous/1.0 (+https://github.com/prometheous)"
DDG_HTML = "https://html.duckduckgo.com/html/"
SERPAPI_URL = "https://serpapi.com/search"


def _fetch(url: str, *, method: str = "GET", data: Optional[bytes] = None, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_ddg_html(html: str, num_results: int) -> List[Dict[str, str]]:
    """Parse DuckDuckGo HTML results without BeautifulSoup."""
    results: List[Dict[str, str]] = []
    # Match result blocks: title link + optional snippet
    for block in re.split(r'<div class="result\s', html)[1:]:
        title_m = re.search(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if not title_m:
            continue
        url = unescape(title_m.group(1).strip())
        title = re.sub(r"<[^>]+>", "", title_m.group(2))
        title = unescape(re.sub(r"\s+", " ", title)).strip()

        snippet_m = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        snippet = ""
        if snippet_m:
            snippet = re.sub(r"<[^>]+>", "", snippet_m.group(1))
            snippet = unescape(re.sub(r"\s+", " ", snippet)).strip()

        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
        if len(results) >= num_results:
            break
    return results


def _search_serpapi(query: str, num_results: int, api_key: str) -> List[Dict[str, str]]:
    params = urllib.parse.urlencode({
        "q": query,
        "api_key": api_key,
        "num": num_results,
        "engine": "google",
    })
    raw = _fetch(f"{SERPAPI_URL}?{params}")
    data = json.loads(raw)
    out: List[Dict[str, str]] = []
    for item in data.get("organic_results", [])[:num_results]:
        out.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return out


def _search_duckduckgo(query: str, num_results: int) -> List[Dict[str, str]]:
    body = urllib.parse.urlencode({"q": query}).encode("utf-8")
    html = _fetch(DDG_HTML, method="POST", data=body)
    return _parse_ddg_html(html, num_results)


def search_web(query: str, num_results: int = 5) -> Dict[str, Any]:
    """
    Search the web. Returns structured results for agents / Telegram / MCP.

    Optional env: ``SERPAPI_API_KEY`` for higher-quality results.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "empty query", "query": query, "results": []}

    num_results = max(1, min(int(num_results), 10))
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()

    try:
        if api_key:
            results = _search_serpapi(query, num_results, api_key)
            provider = "serpapi"
        else:
            results = _search_duckduckgo(query, num_results)
            provider = "duckduckgo"
    except urllib.error.HTTPError as exc:
        return {
            "error": f"HTTP {exc.code}: {exc.reason}",
            "query": query,
            "results": [],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "query": query,
            "results": [],
        }

    return {
        "query": query,
        "provider": provider,
        "count": len(results),
        "results": results,
    }


def format_results_for_chat(payload: Dict[str, Any], *, max_len: int = 3500) -> str:
    """Format search results for Telegram / chat."""
    if payload.get("error"):
        return f"Web search failed: {payload['error']}"

    lines = [f"🔍 Web search: {payload.get('query', '')}"]
    lines.append(f"({payload.get('count', 0)} results via {payload.get('provider', '?')})")
    lines.append("")

    for i, hit in enumerate(payload.get("results") or [], 1):
        title = hit.get("title") or "Untitled"
        url = hit.get("url") or ""
        snippet = (hit.get("snippet") or "")[:200]
        block = f"{i}. {title}\n{url}"
        if snippet:
            block += f"\n{snippet}"
        lines.append(block)
        lines.append("")
        if sum(len(x) + 1 for x in lines) > max_len:
            lines.append("…(truncated)")
            break

    if payload.get("count", 0) == 0:
        lines.append("No results found. Try different keywords.")

    return "\n".join(lines).strip()