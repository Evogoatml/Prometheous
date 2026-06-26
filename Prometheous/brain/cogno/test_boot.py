"""
cogno/boot/test_boot.py

Real pytest tests for cogno boot diagnostics.
Every test actually executes real code paths.
No mocks. No fixtures that fake behavior.
"""

import pytest
import time
from cogno.orchestrator import (
    Thinker, Memory, Scanner, SecurityBridge,
    Signal, SignalType, ChoiceType, FrictionState,
    CognitiveProfile, OrchestratorRole, ModuleStatus,
    test_thinker, test_memory, test_scanner,
    test_security_bridge, _run_halt_cycle, test_friction,
    probe_orchestrator, CognitiveSubstrate
)


# ─────────────────────────────────────────────
# FIXTURES — real objects, no mocks
# ─────────────────────────────────────────────

@pytest.fixture
def thinker():
    return Thinker(depth=2, dual=False)


@pytest.fixture
def memory():
    return Memory(scope="session")


@pytest.fixture
def scanner():
    return Scanner(sensitivity=0.5)


@pytest.fixture
def bridge():
    return SecurityBridge(agent_id="test_agent")


@pytest.fixture
def profile():
    return CognitiveProfile(
        role=OrchestratorRole.COORDINATOR,
        peripheral_sensitivity=0.7,
        friction_threshold=3,
        thought_depth=2,
        memory_scope="session",
        dual_brain=True,
        security_level="standard",
        agent_id="test_agent"
    )


# ─────────────────────────────────────────────
# REAL TESTS
# ─────────────────────────────────────────────

def test_thinker_real(thinker):
    result = test_thinker(thinker)
    assert result.passed, f"thinker failed: {result.detail}"
    assert result.latency_ms >= 0


def test_memory_real(memory):
    result = test_memory(memory)
    assert result.passed, f"memory failed: {result.detail}"


def test_scanner_real(scanner):
    result = test_scanner(scanner)
    assert result.passed, f"scanner failed: {result.detail}"


def test_security_bridge_real(bridge):
    result = test_security_bridge(bridge)
    assert result.passed, f"bridge failed: {result.detail}"


def test_halt_cycle_real(bridge):
    result = _run_halt_cycle(bridge, "test_agent")
    assert result.passed, f"halt cycle failed: {result.detail}"


def test_friction_real(profile):
    result = test_friction(profile)
    assert result.passed, f"friction failed: {result.detail}"


def test_full_attach():
    """Full substrate attach — real end to end."""
    class TestOrchestrator:
        def coordinate(self): pass

    substrate = CognitiveSubstrate()
    port = substrate.attach(TestOrchestrator())

    assert port is not None
    assert port.profile.role == OrchestratorRole.COORDINATOR
    assert port.boot.ready

    # real think
    thought = port.think("test input")
    assert thought.choice in list(ChoiceType)
    assert 0.0 <= thought.confidence <= 1.0

    # real memory
    key = port.remember("test", {"val": 99})
    assert port.recall(key)["val"] == 99

    # real scanner
    port.alert("test_signal", 0.9)
    assert "test_signal" in port.scan()

    # real friction
    tangled = port.add_friction(3, "test tangle")
    assert tangled is True

    # real signal
    port.signal(SignalType.ACTION_INTENT, {"action": "test"})
    assert port._bridge.pending() >= 1


def test_probe_roles():
    """Probe detects roles correctly from real class attributes."""
    class SecurityOrch:
        pass

    class ResearchOrch:
        def search(self): pass

    class CoordOrch:
        def coordinate(self): pass

    assert probe_orchestrator(SecurityOrch()) == OrchestratorRole.SECURITY
    assert probe_orchestrator(CoordOrch()) == OrchestratorRole.COORDINATOR


def test_memory_scope_isolation():
    """Session and task memories don't bleed into each other."""
    session_mem = Memory(scope="session")
    task_mem    = Memory(scope="task")

    k1 = session_mem.store("x", {"scope": "session"})
    k2 = task_mem.store("x", {"scope": "task"})

    assert session_mem.recall(k1)["scope"] == "session"
    assert task_mem.recall(k2)["scope"] == "task"
    assert session_mem.recall(k2) is None
    assert task_mem.recall(k1) is None


def test_friction_threshold_boundary(profile):
    """Friction hits exactly at threshold — not before."""
    friction = FrictionState(threshold=profile.friction_threshold)

    for i in range(profile.friction_threshold - 1):
        friction.add(1, f"step_{i}")
        assert not friction.tangled, f"tangled too early at step {i}"

    friction.add(1, "final_step")
    assert friction.tangled, "should be tangled at threshold"

    friction.clear()
    assert friction.score == 0
    assert not friction.tangled
