"""
Plugin / registry system.

Dynamic registration of agents, memory backends, learning strategies,
and symbolic modules. Config-driven or code discovery.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

from .interfaces import Agent, LearningStrategy, MemoryBackend, SymbolicReasoner

logger = logging.getLogger("si_orchestrator.registry")

T = TypeVar("T")


class Registry:
    """In-process plugin registry with optional JSON bootstrap."""

    def __init__(self) -> None:
        self.memory: Dict[str, MemoryBackend] = {}
        self.learning: Dict[str, LearningStrategy] = {}
        self.symbolic: Dict[str, SymbolicReasoner] = {}
        self.agents: Dict[str, Agent] = {}
        self._factories: Dict[str, Dict[str, Callable[[], Any]]] = {
            "memory": {},
            "learning": {},
            "symbolic": {},
            "agents": {},
        }

    # --- register instances ---
    def register_memory(self, backend: MemoryBackend, name: Optional[str] = None) -> None:
        key = name or backend.name
        self.memory[key] = backend
        logger.info("registered memory backend: %s", key)

    def register_learning(self, strategy: LearningStrategy, name: Optional[str] = None) -> None:
        key = name or strategy.name
        self.learning[key] = strategy
        logger.info("registered learning strategy: %s", key)

    def register_symbolic(self, reasoner: SymbolicReasoner, name: Optional[str] = None) -> None:
        key = name or reasoner.name
        self.symbolic[key] = reasoner
        logger.info("registered symbolic reasoner: %s", key)

    def register_agent(self, agent: Agent, name: Optional[str] = None) -> None:
        key = name or agent.name
        self.agents[key] = agent
        logger.info("registered agent: %s", key)

    def register_factory(self, kind: str, name: str, factory: Callable[[], Any]) -> None:
        if kind not in self._factories:
            raise KeyError(f"unknown kind: {kind}")
        self._factories[kind][name] = factory

    # --- resolve ---
    def get_memory(self, name: str = "default") -> MemoryBackend:
        if name not in self.memory:
            raise KeyError(f"memory backend not found: {name}")
        return self.memory[name]

    def get_learning(self, name: str = "default") -> LearningStrategy:
        if name not in self.learning:
            raise KeyError(f"learning strategy not found: {name}")
        return self.learning[name]

    def get_symbolic(self, name: str = "default") -> SymbolicReasoner:
        if name not in self.symbolic:
            raise KeyError(f"symbolic reasoner not found: {name}")
        return self.symbolic[name]

    def get_agent(self, name: str) -> Agent:
        if name not in self.agents:
            raise KeyError(f"agent not found: {name}")
        return self.agents[name]

    def summary(self) -> Dict[str, List[str]]:
        return {
            "memory": list(self.memory.keys()),
            "learning": list(self.learning.keys()),
            "symbolic": list(self.symbolic.keys()),
            "agents": list(self.agents.keys()),
        }

    def load_from_config(self, plugins: Dict[str, Any]) -> None:
        """
        plugins config shape:
          {
            "memory": [{"name": "json", "class": "si_orchestrator.memory.json_backend.JsonMemoryBackend", "args": {...}}],
            ...
          }
        """
        for kind, items in (plugins or {}).items():
            if not items:
                continue
            for item in items:
                cls_path = item.get("class")
                name = item.get("name")
                args = item.get("args") or {}
                if not cls_path:
                    continue
                obj = _import_and_construct(cls_path, args)
                if kind == "memory":
                    self.register_memory(obj, name=name)
                elif kind == "learning":
                    self.register_learning(obj, name=name)
                elif kind == "symbolic":
                    self.register_symbolic(obj, name=name)
                elif kind in ("agents", "agent"):
                    self.register_agent(obj, name=name)
                else:
                    logger.warning("unknown plugin kind: %s", kind)


def _import_and_construct(class_path: str, args: Dict[str, Any]) -> Any:
    module_path, _, cls_name = class_path.rpartition(".")
    if not module_path:
        raise ValueError(f"invalid class path: {class_path}")
    mod = importlib.import_module(module_path)
    cls = getattr(mod, cls_name)
    return cls(**args)
