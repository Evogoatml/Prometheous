"""
Ghost Sentinel — Adaptive CRDT + Rolling Manchester Polymorphic MCP.

MCP here means *Manchester Cryptographic Protocol* (wire/security layer), not the
Model Context Protocol in ``mcp/server.py``.
"""

from ghost_sentinel.adaptive_crdt import AdaptiveCRDT
from ghost_sentinel.adaptive_policy import AdaptivePolicy
from ghost_sentinel.policy_crdt import PolicyState
from ghost_sentinel.crypto_seed import crypto_backend, derive_swarm_seed
from ghost_sentinel.mcp_codec import MCPCodec, MCPConfig
from ghost_sentinel.policy_crdt import PolicyCRDT
from ghost_sentinel.rolling_manchester import RollingManchester
from ghost_sentinel.swarm import GhostSentinelSwarm
from ghost_sentinel.tool_assembly import ToolAssemblyEngine
from ghost_sentinel.tool_registry import ToolRegistryCRDT, ToolSpec
from ghost_sentinel.relay import CompositeRelayTransport, build_relay_transport
from ghost_sentinel.transport import FileRelayTransport

__all__ = [
    "AdaptiveCRDT",
    "AdaptivePolicy",
    "PolicyCRDT",
    "PolicyState",
    "MCPCodec",
    "MCPConfig",
    "RollingManchester",
    "derive_swarm_seed",
    "crypto_backend",
    "GhostSentinelSwarm",
    "FileRelayTransport",
    "CompositeRelayTransport",
    "build_relay_transport",
    "ToolAssemblyEngine",
    "ToolRegistryCRDT",
    "ToolSpec",
]

__version__ = "0.2.0"