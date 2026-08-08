"""
Self-optimization: profiling, efficiency analysis, load-based tuning.
Adapted from adaptive_vault efficiency_engine + performance_profiler + recommendation_engine.
No governance / policy gates.
"""
from __future__ import annotations

import functools
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any, Callable

from utils.config import cfg

LEARNING_DIR = cfg.DATA_DIR / "learning"
PROFILE_LOG = LEARNING_DIR / "performance_profile.jsonl"
SUMMARY_FILE = LEARNING_DIR / "efficiency_summary.json"
REPORT_FILE = LEARNING_DIR / "recommendations.json"
TUNING_FILE = LEARNING_DIR / "tuning.json"
MAX_REPORTS = 5


def profile(func: Callable) -> Callable:
    """Decorator to measure and record function execution time."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - start
            Optimizer.record_profile(func.__name__, elapsed)
    return wrapper


class Optimizer:
    def __init__(self):
        LEARNING_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def record_profile(name: str, elapsed: float) -> None:
        LEARNING_DIR.mkdir(parents=True, exist_ok=True)
        entry = {"func": name, "elapsed": round(elapsed, 6), "ts": time.time()}
        with open(PROFILE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def read_profiles(self) -> list[dict]:
        if not PROFILE_LOG.exists():
            return []
        with open(PROFILE_LOG, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def analyze_efficiency(self) -> dict | None:
        data = self.read_profiles()
        if not data:
            return None
        avg = statistics.mean(d["elapsed"] for d in data)
        slow = [d for d in data if d["elapsed"] > avg * 1.5]
        summary = {"avg_exec_time": avg, "slow_functions": slow, "sample_count": len(data)}
        with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        return summary

    def generate_recommendations(self) -> list[str]:
        if not SUMMARY_FILE.exists():
            return []
        with open(SUMMARY_FILE, encoding="utf-8") as f:
            summary = json.load(f)
        avg = summary.get("avg_exec_time", 0)
        slow_funcs = summary.get("slow_functions", [])
        recs: list[str] = []

        if avg > 0.2:
            recs.append("Overall latency is high; consider caching or reducing I/O.")
        if len(slow_funcs) > 3:
            recs.append(f"{len(slow_funcs)} slow functions detected; review redundant work.")

        for s in slow_funcs:
            name = s["func"]
            t = s["elapsed"]
            if t > avg * 3:
                recs.append(f"{name} is critically slow ({t:.4f}s). Consider async or batching.")
            elif "check_" in name:
                recs.append(f"{name} called repeatedly; consider batching checks.")
            elif "load" in name:
                recs.append(f"{name} may benefit from memoization.")

        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "recommendations": recs or ["No critical optimizations needed."],
        }
        self._save_report(report)
        return recs

    def _save_report(self, report: dict) -> None:
        data = []
        if REPORT_FILE.exists():
            with open(REPORT_FILE, encoding="utf-8") as f:
                data = json.load(f)
        data.append(report)
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(data[-MAX_REPORTS:], f, indent=2)

    def get_recommendations(self) -> list[str]:
        if not REPORT_FILE.exists():
            return []
        with open(REPORT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return []
        return data[-1].get("recommendations", [])

    def auto_tune(self) -> dict:
        """Adjust swarm parallelism based on system load."""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory().percent
        except ImportError:
            return {"status": "skipped", "reason": "psutil not installed"}

        tuning = self.get_tuning()
        base_parallel = int(os.getenv("PROM_SWARM_MAX_PARALLEL", str(cfg.SWARM_MAX_PARALLEL)))

        if cpu > 85 or mem > 85:
            tuning["swarm_max_parallel"] = max(1, base_parallel - 1)
            tuning["reason"] = "high_load"
        elif cpu < 30 and mem < 50:
            tuning["swarm_max_parallel"] = min(base_parallel + 1, 8)
            tuning["reason"] = "low_load"
        else:
            tuning["swarm_max_parallel"] = base_parallel
            tuning["reason"] = "stable"

        tuning.update({"cpu": cpu, "mem": mem, "ts": time.time()})
        with open(TUNING_FILE, "w", encoding="utf-8") as f:
            json.dump(tuning, f, indent=2)
        return tuning

    def get_tuning(self) -> dict:
        if TUNING_FILE.exists():
            with open(TUNING_FILE, encoding="utf-8") as f:
                return json.load(f)
        return {"swarm_max_parallel": cfg.SWARM_MAX_PARALLEL}