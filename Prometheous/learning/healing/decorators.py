"""
@self_healing — log proposals on failure, never mutate source.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def self_healing(func: F) -> F:
    """
    Wrap an agent method: on exception, record a healing proposal and re-raise.

    The caller (orchestrator) may also call handle_failure directly.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        agent_name = None
        if args and hasattr(args[0], "name"):
            agent_name = getattr(args[0], "name", None)

        try:
            return func(*args, **kwargs)
        except Exception as exc:
            from learning.healing import handle_failure

            payload = kwargs.get("payload")
            if payload is None and len(args) > 1 and isinstance(args[1], dict):
                payload = args[1]

            healing = handle_failure(
                exc,
                agent=agent_name,
                payload=payload if isinstance(payload, dict) else None,
            )
            logger.info(
                "self_healing proposal=%s exc=%s strategy=%s",
                healing.get("proposal_id"),
                healing.get("exc_type"),
                healing.get("best_strategy"),
            )
            exc._healing = healing  # type: ignore[attr-defined]
            raise

    return wrapper  # type: ignore[return-value]