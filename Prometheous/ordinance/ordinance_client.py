"""
Ordinance client — referenced by AGENT.md for folder context queries.
Stub for Prometheus compatibility.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class OrdinanceClient:
    """Client for querying folder context. Stub."""

    def get_folder_context(self, path: str) -> Dict[str, Any]:
        logger.debug(f"Ordinance: get_folder_context({path})")
        return {"path": path, "files": [], "status": "stub"}

    def search(self, query: str) -> List[Dict[str, Any]]:
        logger.debug(f"Ordinance: search({query})")
        return []