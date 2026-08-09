"""Parallel DAG execution for mosaic tiles."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from inspect import signature
from typing import Any, Callable, Dict, List, Optional

try:
    from core.mosaic.blackboard import Blackboard
    from core.mosaic.tiles import TileSpec
except Exception:
    Blackboard = None
    TileSpec = Any

logger = logging.getLogger(__name__)


class DAGExecutor:
    """Execute dependency-aware mosaic tiles in parallel batches."""

    def __init__(self) -> None:
        self.graph: Dict[str, List[str]] = {}

    def add_tile(self, name: str, deps: List[str] = None) -> None:
        self.graph[name] = list(deps or [])
        for dep in deps or []:
            self.graph.setdefault(dep, [])

    def execution_order(self) -> List[List[str]]:
        graph = {name: list(deps) for name, deps in self.graph.items()}
        remaining = set(graph.keys())
        batches: List[List[str]] = []
        while remaining:
            ready = sorted(name for name in remaining if not [dep for dep in graph.get(name, []) if dep in remaining])
            if not ready:
                logger.warning("cycle detected in DAGExecutor graph; falling back to remaining order")
                batches.append(sorted(remaining))
                break
            batches.append(ready)
            for name in ready:
                remaining.discard(name)
        return batches

    def run_parallel(
        self,
        tiles: List[TileSpec],
        goal: str,
        payload: Dict[str, Any],
        agent_runner: Callable[..., Dict[str, Any]],
        max_workers: int = 4,
    ) -> List[Dict[str, Any]]:
        tile_map = {getattr(tile, "name", f"tile_{index}"): tile for index, tile in enumerate(tiles or [])}
        if not self.graph:
            for name in tile_map:
                self.add_tile(name)
        else:
            for name in tile_map:
                self.graph.setdefault(name, [])

        blackboard = Blackboard(goal=goal) if Blackboard is not None else None
        ordered_results: Dict[str, Dict[str, Any]] = {}
        for batch in self.execution_order():
            active = [name for name in batch if name in tile_map]
            if not active:
                continue
            with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(active)))) as executor:
                futures = {
                    executor.submit(self._invoke_runner, agent_runner, tile_map[name], goal, payload, blackboard): name
                    for name in active
                }
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"status": "failed", "tile": name, "error": str(exc)}
                    ordered_results[name] = result if isinstance(result, dict) else {"status": "ok", "tile": name, "result": result}
                    if blackboard is not None:
                        if ordered_results[name].get("status") == "failed":
                            blackboard.fail(name, ordered_results[name].get("error", "unknown error"))
                        else:
                            blackboard.write(name, ordered_results[name])
        results = [ordered_results[name] for name in tile_map if name in ordered_results]
        merged = self.merge_results(results)
        if blackboard is not None:
            merged["blackboard"] = blackboard.snapshot()
        return results + [{"status": merged.get("status", "ok"), "merged": merged}]

    def merge_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {"status": "ok", "results": [], "formatted": ""}
        formatted_parts: List[str] = []
        for result in results or []:
            if not isinstance(result, dict):
                continue
            merged["results"].append(result)
            if result.get("status") in {"failed", "error"}:
                merged["status"] = "failed"
            text = result.get("formatted") or result.get("message") or result.get("result")
            if isinstance(text, str) and text:
                formatted_parts.append(text)
            elif isinstance(text, dict):
                formatted_parts.append(str(text))
            for key, value in result.items():
                if key in {"status", "formatted", "message", "result"}:
                    continue
                if key not in merged:
                    merged[key] = value
        merged["formatted"] = "\n".join(formatted_parts)
        return merged

    @staticmethod
    def _invoke_runner(
        agent_runner: Callable[..., Dict[str, Any]],
        tile: TileSpec,
        goal: str,
        payload: Dict[str, Any],
        blackboard: Optional[Any],
    ) -> Dict[str, Any]:
        run_payload = dict(payload or {})
        run_payload.setdefault("goal", goal)
        run_payload.setdefault("tile", getattr(tile, "name", "unknown"))
        try:
            params = signature(agent_runner).parameters
        except Exception:
            params = None
        if params is None:
            return agent_runner(tile, goal, run_payload, blackboard)
        kwargs: Dict[str, Any] = {}
        if "tile" in params:
            kwargs["tile"] = tile
        if "goal" in params:
            kwargs["goal"] = goal
        if "payload" in params:
            kwargs["payload"] = run_payload
        if "blackboard" in params:
            kwargs["blackboard"] = blackboard
        if kwargs:
            return agent_runner(**kwargs)
        count = len(params)
        if count == 0:
            return agent_runner()
        if count >= 4:
            return agent_runner(tile, goal, run_payload, blackboard)
        if count == 3:
            return agent_runner(tile, goal, run_payload)
        if count == 2:
            return agent_runner(tile, run_payload)
        if count == 1:
            return agent_runner(run_payload)
        return agent_runner()
