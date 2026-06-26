"""
Generic utility helpers. No LLM, no system logic — just utilities.
"""
import json
import hashlib
import time
import logging
from typing import Any, Callable, Dict, Optional
from datetime import datetime
from functools import wraps


def generate_id(prefix: str = "") -> str:
    """Generate unique ID with timestamp + hash."""
    timestamp = str(time.time_ns()).encode()
    short_hash = hashlib.sha256(timestamp).hexdigest()[:12]
    return f"{prefix}{short_hash}" if prefix else short_hash


def safe_json_loads(data: str, default: Any = None) -> Any:
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(data: Any, indent: int = 2) -> str:
    try:
        return json.dumps(data, indent=indent, default=str)
    except (TypeError, ValueError) as e:
        return json.dumps({"error": str(e), "data_type": str(type(data))})


def timestamp() -> str:
    return datetime.utcnow().isoformat()


def truncate_string(s: str, max_length: int = 100, suffix: str = "...") -> str:
    if len(s) <= max_length:
        return s
    return s[: max_length - len(suffix)] + suffix


def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Retry decorator with exponential backoff."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            current_delay = delay
            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    logging.getLogger(func.__module__).warning(
                        "%s attempt %d failed: %s. Retrying in %.1fs",
                        func.__name__, attempt, e, current_delay,
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator
