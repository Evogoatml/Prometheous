"""Cogno — quantum-inspired cognitive computing subsystem."""

from .orchestrator import CognitiveSubstrate, CognitivePort, SubstrateNotReady

__version__ = "0.1.0"
__all__ = [
    "CognitiveSubstrate",
    "CognitivePort",
    "SubstrateNotReady",
    "orchestrator",
    "entanglement",
    "boot",
    "core",
    "crypto",
    "nodes",
]
