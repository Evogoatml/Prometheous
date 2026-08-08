"""
Polymorphic Auto-Mosaic — adaptive agentic assembly for Prometheous.

A mosaic is a temporary composition of capability tiles that:
  1. Assembles itself from a goal (auto)
  2. Morphs role/constraints per cognitive profile (polymorphic)
  3. Acts through real agents/tools (agentic)
  4. Retries / re-routes on failure (adaptive)
  5. Emits work product + trajectory for synthetic learning (gen)

This is the spine of Prometheous synthetic intelligence — not a chat wrapper.
"""
from core.mosaic.runtime import MosaicRuntime, MosaicResult, get_mosaic
from core.mosaic.polymorphic import PolymorphicAgentSystem

__all__ = [
    "MosaicRuntime",
    "MosaicResult",
    "get_mosaic",
    "PolymorphicAgentSystem",
]
