# modules/performance_profiler.py
"""
Performance Profiler
Records runtime latency of key functions for efficiency optimization.
"""

import time, json, functools, os

PROFILE_LOG = "audit/performance_profile.json"

def ensure_log():
    os.makedirs(os.path.dirname(PROFILE_LOG), exist_ok=True)
    if not os.path.exists(PROFILE_LOG):
        with open(PROFILE_LOG, "w") as f:
            f.write("")

def record_profile(name, elapsed):
    ensure_log()
    entry = {"func": name, "elapsed": round(elapsed, 6), "ts": time.time()}
    with open(PROFILE_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")

def profile(func):
    """Decorator to measure and record function execution time."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        record_profile(func.__name__, elapsed)
        return result
    return wrapper
