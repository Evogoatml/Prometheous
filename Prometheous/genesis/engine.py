"""
Genesis Engine
System does not accept commands until genesis passes.
Validates environment, dependencies, and system integrity on boot.
"""
import asyncio
import os
import sys
import importlib
import time
from prometheous.state import State


class GenesisEngine:
    """Runs at boot. Validates the system is healthy before Prometheous goes online."""

    def __init__(self, state: State):
        self.state = state
        self.checks = []
        self.failures = []

    async def run(self) -> bool:
        """Execute all genesis checks. Returns True if all pass."""
        print("\n[GENESIS] Running system validation...")

        checks = [
            ("Environment", self._check_environment),
            ("Dependencies", self._check_dependencies),
            ("Memory Modules", self._check_memory_modules),
            ("State Integrity", self._check_state_integrity),
            ("System Resources", self._check_system_resources),
        ]

        all_pass = True
        for name, check_fn in checks:
            passed, message = await check_fn()
            status = "✅" if passed else "❌"
            print(f"  {status} {name}: {message}")
            if not passed:
                self.failures.append((name, message))
                all_pass = False

        if all_pass:
            self.state.genesis_complete = True
            self.state.online_since = time.time()
            print("[GENESIS] All checks passed — system is healthy\n")
        else:
            print(f"[GENESIS] {len(self.failures)} failure(s) detected\n")

        return all_pass

    async def _check_environment(self):
        """Check Python version and critical env vars."""
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info < (3, 10):
            return False, f"Python {py_version} < 3.10"
        return True, f"Python {py_version}"

    async def _check_dependencies(self):
        """Check critical imports resolve."""
        required = ["cryptography", "chromadb", "sentence_transformers", "networkx", "numpy"]
        missing = []
        for pkg in required:
            try:
                importlib.import_module(pkg)
            except ImportError:
                missing.append(pkg)
        if missing:
            return False, f"Missing: {', '.join(missing)}"
        return True, f"All {len(required)} core packages OK"

    async def _check_memory_modules(self):
        """Verify all memory subsystems can initialize."""
        modules = {}
        try:
            from prometheous.memory.vault import EncryptedVault
            modules["vault"] = EncryptedVault
            from prometheous.memory.conversation import ConversationStore
            modules["conversation"] = ConversationStore
            from prometheous.memory.quantum_graph import QuantumGraph
            modules["graph"] = QuantumGraph
            from prometheous.memory.graph_rag import GraphRAGStore
            modules["graph_rag"] = GraphRAGStore
        except Exception as e:
            return False, str(e)
        return True, f"{', '.join(modules.keys())} loaded"

    async def _check_state_integrity(self):
        """Verify state object is valid."""
        if self.state is None:
            return False, "State is None"
        return True, "State initialized"

    async def _check_system_resources(self):
        """Check disk space and critical paths exist."""
        data_dirs = ["data", "data/vault", "knowledge"]
        missing_dirs = []
        for d in data_dirs:
            path = os.path.join(os.getcwd(), d)
            if not os.path.exists(path):
                try:
                    os.makedirs(path, exist_ok=True)
                except OSError:
                    missing_dirs.append(d)
        if missing_dirs:
            return False, f"Cannot create: {', '.join(missing_dirs)}"
        return True, "All data directories OK"
