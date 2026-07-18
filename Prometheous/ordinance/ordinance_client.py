"""
Ordinance client — on-demand folder context for Prometheous agents.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class OrdinanceClient:
    """Query folder context from the on-demand folder index."""

    def get_folder_context(self, path: str) -> Dict[str, Any]:
        logger.debug("Ordinance: get_folder_context(%s)", path)
        try:
            from knowledge.folder_index import scan_folder
            return scan_folder(path)
        except FileNotFoundError as exc:
            return {"status": "error", "error": str(exc), "path": path}
        except (ValueError, NotADirectoryError) as exc:
            return {"status": "error", "error": str(exc), "path": path}
        except Exception as exc:
            logger.debug("folder context failed", exc_info=True)
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}", "path": path}

    def search(self, query: str) -> List[Dict[str, Any]]:
        logger.debug("Ordinance: search(%s)", query)
        try:
            from knowledge.folder_index import search_folders
            return search_folders(query)
        except Exception as exc:
            logger.debug("folder search failed", exc_info=True)
            return [{"status": "error", "error": str(exc)}]