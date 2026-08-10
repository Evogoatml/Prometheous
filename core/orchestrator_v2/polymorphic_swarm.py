"""
Compatibility shim.

core/orchestrator.py is a module, so core.orchestrator.* subimports fail.
The package was renamed core/orchestrator_v2/ to remove the collision.
Import from core.mosaic instead:

    from core.mosaic import PolymorphicAgentSystem
"""
from core.mosaic.polymorphic import PolymorphicAgentSystem

__all__ = ["PolymorphicAgentSystem"]
