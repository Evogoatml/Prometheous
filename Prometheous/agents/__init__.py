
"""
Agent registry.

Two-tier discovery:
  - swarm/nodes.DEFAULT_NODES  — built-in specialists (scan, recon, report, etc.)
  - agents/                    — user-installed specialist modules

Each module in agents/ must define a class with:
  - name: str  (unique identifier)
  - role / specialty (optional but used for display)

The registry exposes:
  - register_all(orb)  — register everything with the swarm orchestrator
  - list()             — list known agent classes
"""
import importlib
import logging
import pkgutil
from pathlib import Path
from typing import List, Type

logger = logging.getLogger(__name__)


# Built-in swarm nodes (scanner, recon, exploit, ...)
try:
    from swarm.nodes import DEFAULT_NODES  # type: ignore
except ImportError:
    DEFAULT_NODES = []


def register_all(orb) -> None:
    """Register built-in swarm nodes + all agents/ in agents/."""
    # 1. Built-ins
    for cls in DEFAULT_NODES:
        orb.register_class(cls)
        logger.debug("registered built-in: %s", cls.name)

    # 2. agents/ directory
    agents_pkg = Path(__file__).parent
    for mod in pkgutil.iter_modules([str(agents_pkg)]):
        if mod.name.startswith("_"):
            continue
        full = f"agents.{mod.name}"
        try:
            m = importlib.import_module(full)
            for attr in dir(m):
                obj = getattr(m, attr)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, object)
                    and obj is not object
                    and obj.__module__ == full
                    and hasattr(obj, "name")
                    and obj is not type
                    # filter out BaseAgent itself and other infra
                    and getattr(obj, "__module__", "") == full
                ):
                    try:
                        orb.register_class(obj)
                        break  # one agent class per module is enough
                    except Exception as e:
                        logger.exception("failed to register %s from %s: %s", attr, full, e)
        except Exception as e:
            logger.debug("skip agents/%s: %s", mod.name, e)


def list_agents() -> List[str]:
    names = []
    for cls in DEFAULT_NODES:
        names.append(cls.name)
    agents_pkg = Path(__file__).parent
    for mod in pkgutil.iter_modules([str(agents_pkg)]):
        full = f"agents.{mod.name}"
        try:
            m = importlib.import_module(full)
            for attr in dir(m):
                obj = getattr(m, attr)
                if (
                    isinstance(obj, type)
                    and obj.__module__ == full
                    and hasattr(obj, "name")
                    and getattr(obj, "name", None)
                ):
                    names.append(obj.name)
                    break
        except Exception:
            pass
    return names
