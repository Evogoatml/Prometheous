"""
Web search agent — DuckDuckGo / SerpAPI for Prometheous.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from tools.web_search import format_results_for_chat, search_web


def _extract_query(payload: Dict[str, Any]) -> str:
    for key in ("query", "q", "search", "target"):
        val = payload.get(key)
        if val:
            return str(val).strip()

    msg = (payload.get("user_msg") or "").strip()
    if not msg:
        return ""

    patterns = [
        r"(?:search(?:\s+the\s+web)?\s+for|look\s+up|google|web\s+search)\s+(.+)",
        r"^search\s+(.+)",
        r"^/search\s+(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, msg, re.I)
        if m:
            return m.group(1).strip().strip("?")

    return msg


class WebSearchAgent:
    name = "web_search"
    role = "WebSearch"
    specialty = "web search via DuckDuckGo or SerpAPI"
    tasks_completed = 0

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        query = _extract_query(payload)
        if not query:
            return {
                "status": "failed",
                "agent": self.name,
                "error": "no search query — try: search quantum computing",
            }

        num = int(payload.get("num_results") or payload.get("limit") or 5)
        result = search_web(query, num_results=num)
        result["status"] = "ok" if not result.get("error") else "failed"
        result["agent"] = self.name
        result["formatted"] = format_results_for_chat(result)
        return result