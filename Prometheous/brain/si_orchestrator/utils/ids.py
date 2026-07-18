"""ID helpers."""

from __future__ import annotations

import time
import uuid


def new_id(prefix: str = "id") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}-{int(time.time()) % 100000}"
