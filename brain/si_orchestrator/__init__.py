"""
Synthetic Intelligence Orchestrator (Phase 1 MVP).

Modular, extensible design for memory recall and learning under Prometheous.
"""

__version__ = "0.1.0"
__schema_version__ = "1.0.0"

from .core.orchestrator import SIOrchestrator
from .core.registry import Registry

__all__ = ["SIOrchestrator", "Registry", "__version__", "__schema_version__"]
