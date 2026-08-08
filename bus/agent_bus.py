"""
Simple in-process event bus for agent communication.
"""
import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class AgentBus:
    """Lightweight pub-sub event bus for agent coordination."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event: str, handler: Callable):
        self._subscribers.setdefault(event, []).append(handler)

    def publish_sync(self, event: str, data: Dict[str, Any], source: str = "unknown"):
        logger.debug(f"[Bus] {source} → {event}: {str(data)[:100]}")
        for handler in self._subscribers.get(event, []):
            try:
                handler(data)
            except Exception as e:
                logger.error(f"[Bus] handler error on {event}: {e}")

    def publish(self, event: str, data: Dict[str, Any], source: str = "unknown"):
        """Async-compatible alias for publish_sync."""
        self.publish_sync(event, data, source)


bus = AgentBus()