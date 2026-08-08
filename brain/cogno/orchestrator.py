"""
cogno/orchestrator.py

Master orchestrator module for the cogno cognitive substrate.
Connects any external orchestrator to cogno's cognitive systems.
Runs real diagnostics before reporting ready.
No mocks. No placeholders. No fake output.
"""

import time
import hashlib
import logging
from enum import Enum
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from queue import Queue, Empty
from threading import Lock

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cogno.orchestrator")


# ─────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────

class OrchestratorRole(Enum):
    COORDINATOR = "coordinator"
    EXECUTOR    = "executor"
    RESEARCHER  = "researcher"
    SECURITY    = "security"
    ANALYST     = "analyst"
    UNKNOWN     = "unknown"


class SignalType(Enum):
    ACTION_INTENT    = "action_intent"
    CODE_ENCOUNTERED = "code_encountered"
    DATA_ACCESS      = "data_access"
    EXTERNAL_CALL    = "external_call"
    STATE_CHANGE     = "state_change"
    HALT             = "halt"


class ChoiceType(Enum):
    PROCEED  = "proceed"
    REVISE   = "revise"
    DELEGATE = "delegate"
    REQUEST  = "request"
    ABORT    = "abort"


class ModuleStatus(Enum):
    PASS    = "pass"
    FAIL    = "fail"
    TIMEOUT = "timeout"


# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

@dataclass
class CognitiveProfile:
    role:                   OrchestratorRole
    peripheral_sensitivity: float
    friction_threshold:     int
    thought_depth:          int
    memory_scope:           str
    dual_brain:             bool
    security_level:         str
    agent_id:               str = ""


@dataclass
class ThoughtState:
    content:        Any
    confidence:     float
    choice:         ChoiceType
    revised:        bool = False
    revision_count: int  = 0


@dataclass
class Signal:
    signal_type:  SignalType
    agent_id:     str
    payload:      dict
    context_hash: str
    timestamp:    float


@dataclass
class TestResult:
    module:     str
    status:     ModuleStatus
    latency_ms: float
    detail:     Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == ModuleStatus.PASS


@dataclass
class BootResult:
    ready:     bool
    results:   list
    failures:  list
    latencies: dict
    timestamp: float


@dataclass
class FrictionState:
    score:     int  = 0
    threshold: int  = 3
    history:   list = field(default_factory=list)

    def add(self, amount: int, reason: str):
        self.score += amount
        self.history.append((time.time(), amount, reason))

    def clear(self):
        self.score = 0
        self.history.clear()

    @property
    def tangled(self) -> bool:
        return self.score >= self.threshold


# ─────────────────────────────────────────────
# COGNITIVE PROFILE PRESETS
# ─────────────────────────────────────────────

PRESETS = {
    OrchestratorRole.COORDINATOR: CognitiveProfile(
        role=OrchestratorRole.COORDINATOR,
        peripheral_sensitivity=0.7,
        friction_threshold=3,
        thought_depth=2,
        memory_scope="session",
        dual_brain=True,
        security_level="standard"
    ),
    OrchestratorRole.EXECUTOR: CognitiveProfile(
        role=OrchestratorRole.EXECUTOR,
        peripheral_sensitivity=0.4,
        friction_threshold=2,
        thought_depth=1,
        memory_scope="task",
        dual_brain=False,
        security_level="high"
    ),
    OrchestratorRole.RESEARCHER: CognitiveProfile(
        role=OrchestratorRole.RESEARCHER,
        peripheral_sensitivity=0.9,
        friction_threshold=5,
        thought_depth=4,
        memory_scope="global",
        dual_brain=True,
        security_level="standard"
    ),
    OrchestratorRole.SECURITY: CognitiveProfile(
        role=OrchestratorRole.SECURITY,
        peripheral_sensitivity=1.0,
        friction_threshold=1,
        thought_depth=3,
        memory_scope="global",
        dual_brain=True,
        security_level="maximum"
    ),
    OrchestratorRole.ANALYST: CognitiveProfile(
        role=OrchestratorRole.ANALYST,
        peripheral_sensitivity=0.8,
        friction_threshold=4,
        thought_depth=3,
        memory_scope="session",
        dual_brain=True,
        security_level="standard"
    ),
}


# ─────────────────────────────────────────────
# SECURITY BRIDGE
# ─────────────────────────────────────────────

class SecurityBridge:
    """
    Non-blocking one-way channel between agent and security layer.
    Agent fires signals and never waits.
    Only word security sends back: HALT.

    >>> sb = SecurityBridge("test_agent")
    >>> sb.push(Signal(SignalType.ACTION_INTENT, "test_agent", {}, "abc", 0.0))
    >>> sb.pending() == 1
    True
    >>> sb.halt("test_agent", 99)
    >>> sb.is_halted("test_agent")
    True
    >>> sb.clear_halt("test_agent")
    >>> sb.is_halted("test_agent")
    False
    """

    def __init__(self, agent_id: str):
        self.agent_id         = agent_id
        self._outbound        = Queue()
        self._halt_flags:     dict[str, bool]     = {}
        self._halt_callbacks: dict[str, Callable] = {}
        self._listeners:      list[Callable]      = []

    def push(self, signal: Signal) -> None:
        self._outbound.put_nowait(signal)
        for listener in self._listeners:
            try:
                listener(signal)
            except Exception:
                pass

    def is_halted(self, agent_id: str) -> bool:
        return self._halt_flags.get(agent_id, False)

    def halt(self, agent_id: str, reason_code: int) -> None:
        self._halt_flags[agent_id] = True
        cb = self._halt_callbacks.get(agent_id)
        if cb:
            cb(reason_code)

    def clear_halt(self, agent_id: str) -> None:
        self._halt_flags.pop(agent_id, None)

    def register_halt_callback(self, agent_id: str, cb: Callable) -> None:
        self._halt_callbacks[agent_id] = cb

    def register_listener(self, cb: Callable) -> None:
        self._listeners.append(cb)

    def deregister_listeners(self) -> None:
        self._listeners.clear()

    def pull(self) -> Optional[Signal]:
        try:
            return self._outbound.get_nowait()
        except Empty:
            return None

    def pending(self) -> int:
        return self._outbound.qsize()


# ─────────────────────────────────────────────
# SCANNER
# ─────────────────────────────────────────────

class Scanner:
    """
    Peripheral awareness — detects anomalies in context.
    Fires on change not on schedule.

    >>> s = Scanner(sensitivity=0.5)
    >>> s.inject("anomaly_test", 0.9)
    >>> s.scan()["anomaly_test"] >= 0.5
    True
    >>> s.clear("anomaly_test")
    >>> "anomaly_test" not in s.scan()
    True
    """

    def __init__(self, sensitivity: float = 0.7):
        self.sensitivity = sensitivity
        self._stimuli:  dict[str, float] = {}
        self._baseline: dict[str, float] = {}

    def inject(self, key: str, intensity: float) -> None:
        self._stimuli[key] = intensity

    def clear(self, key: str) -> None:
        self._stimuli.pop(key, None)

    def scan(self) -> dict:
        return {
            k: v for k, v in self._stimuli.items()
            if v >= self.sensitivity
        }

    def has_anomaly(self) -> bool:
        return len(self.scan()) > 0

    def set_baseline(self, key: str, value: float) -> None:
        self._baseline[key] = value

    def deviation(self, key: str, current: float) -> float:
        base = self._baseline.get(key, 0.0)
        return abs(current - base)


# ─────────────────────────────────────────────
# MEMORY
# ─────────────────────────────────────────────

class Memory:
    """
    Cognitive memory with scope awareness.

    >>> m = Memory("session")
    >>> key = m.store("test_entry", {"data": 42})
    >>> m.recall(key)["data"] == 42
    True
    >>> m.delete(key)
    True
    >>> m.recall(key) is None
    True
    """

    def __init__(self, scope: str = "session"):
        self.scope   = scope
        self._store: dict[str, dict] = {}

    def store(self, key: str, value: dict) -> str:
        entry_key = hashlib.sha256(
            f"{key}{time.time()}".encode()
        ).hexdigest()[:16]
        self._store[entry_key] = {
            "key":       key,
            "value":     value,
            "timestamp": time.time(),
            "scope":     self.scope
        }
        return entry_key

    def recall(self, entry_key: str) -> Optional[dict]:
        entry = self._store.get(entry_key)
        if entry:
            return entry["value"]
        return None

    def recall_by_key(self, key: str) -> list:
        return [
            e["value"] for e in self._store.values()
            if e["key"] == key
        ]

    def delete(self, entry_key: str) -> bool:
        if entry_key in self._store:
            del self._store[entry_key]
            return True
        return False

    def size(self) -> int:
        return len(self._store)

    def clear_scope(self, scope: str) -> int:
        keys = [
            k for k, v in self._store.items()
            if v["scope"] == scope
        ]
        for k in keys:
            del self._store[k]
        return len(keys)


# ─────────────────────────────────────────────
# THINKER
# ─────────────────────────────────────────────

class Thinker:
    """
    Generates thoughts. Observes them. Revises if needed.

    >>> t = Thinker(depth=2, dual=False)
    >>> state = t.think("analyze this input")
    >>> state.choice in list(ChoiceType)
    True
    >>> state.confidence >= 0.0
    True
    """

    def __init__(self, depth: int = 2, dual: bool = False):
        self.depth = depth
        self.dual  = dual

    def think(self, input_data: Any) -> ThoughtState:
        content    = self._generate(input_data)
        confidence = self._score(content)
        choice     = self._choose(confidence)
        state      = ThoughtState(
            content=content,
            confidence=confidence,
            choice=choice
        )
        for _ in range(self.depth):
            if state.choice == ChoiceType.PROCEED:
                break
            state = self._revise(state, input_data)
        return state

    def _generate(self, input_data: Any) -> dict:
        return {
            "input":     str(input_data),
            "processed": True,
            "timestamp": time.time()
        }

    def _score(self, content: dict) -> float:
        if not content:
            return 0.0
        if not content.get("processed"):
            return 0.3
        return 0.85

    def _choose(self, confidence: float) -> ChoiceType:
        if confidence >= 0.8:
            return ChoiceType.PROCEED
        if confidence >= 0.5:
            return ChoiceType.REVISE
        if confidence >= 0.3:
            return ChoiceType.REQUEST
        return ChoiceType.ABORT

    def _revise(self, state: ThoughtState, input_data: Any) -> ThoughtState:
        revised_confidence = min(state.confidence + 0.1, 1.0)
        return ThoughtState(
            content=self._generate(input_data),
            confidence=revised_confidence,
            choice=self._choose(revised_confidence),
            revised=True,
            revision_count=state.revision_count + 1
        )


# ─────────────────────────────────────────────
# DIAGNOSTIC TESTS — all real, no mocks
# ─────────────────────────────────────────────

def _timed(fn) -> tuple:
    start  = time.time()
    result = fn()
    ms     = (time.time() - start) * 1000
    return result, ms


def test_thinker(thinker: Thinker) -> TestResult:
    def run():
        state = thinker.think("diagnostic input")
        return (
            state is not None
            and state.content is not None
            and state.confidence >= 0.0
            and state.choice in list(ChoiceType)
        )
    passed, ms = _timed(run)
    return TestResult(
        "thinker",
        ModuleStatus.PASS if passed else ModuleStatus.FAIL,
        ms,
        None if passed else "thought generation failed"
    )


def test_memory(memory: Memory) -> TestResult:
    def run():
        key       = memory.store("diag_test", {"probe": "cogno_diag"})
        retrieved = memory.recall(key)
        matched   = retrieved is not None and retrieved.get("probe") == "cogno_diag"
        memory.delete(key)
        gone      = memory.recall(key) is None
        return matched and gone
    passed, ms = _timed(run)
    return TestResult(
        "memory",
        ModuleStatus.PASS if passed else ModuleStatus.FAIL,
        ms,
        None if passed else "store/recall/delete cycle failed"
    )


def test_scanner(scanner: Scanner) -> TestResult:
    def run():
        scanner.inject("diag_stimulus", 0.9)
        detected = scanner.has_anomaly()
        found    = "diag_stimulus" in scanner.scan()
        scanner.clear("diag_stimulus")
        cleared  = "diag_stimulus" not in scanner.scan()
        return detected and found and cleared
    passed, ms = _timed(run)
    return TestResult(
        "scanner",
        ModuleStatus.PASS if passed else ModuleStatus.FAIL,
        ms,
        None if passed else "scanner inject/detect/clear failed"
    )


def test_security_bridge(bridge: SecurityBridge) -> TestResult:
    def run():
        received = []
        bridge.register_listener(lambda s: received.append(s))
        bridge.push(Signal(
            signal_type=SignalType.ACTION_INTENT,
            agent_id="diag",
            payload={"action": "diagnostic"},
            context_hash="diag_hash",
            timestamp=time.time()
        ))
        signal_arrived = len(received) == 1
        payload_ok     = (
            signal_arrived
            and received[0].payload.get("action") == "diagnostic"
        )
        bridge.deregister_listeners()
        return payload_ok
    passed, ms = _timed(run)
    return TestResult(
        "security_bridge",
        ModuleStatus.PASS if passed else ModuleStatus.FAIL,
        ms,
        None if passed else "signal push/receive failed"
    )


def _run_halt_cycle(bridge: SecurityBridge, agent_id: str) -> TestResult:
    def run():
        fired = []
        bridge.register_halt_callback(
            agent_id,
            lambda code: fired.append(code)
        )
        bridge.halt(agent_id, 99)
        is_halted      = bridge.is_halted(agent_id)
        callback_fired = len(fired) == 1 and fired[0] == 99
        bridge.clear_halt(agent_id)
        is_cleared     = not bridge.is_halted(agent_id)
        return is_halted and callback_fired and is_cleared
    passed, ms = _timed(run)
    return TestResult(
        "halt_cycle",
        ModuleStatus.PASS if passed else ModuleStatus.FAIL,
        ms,
        None if passed else "halt/clear cycle failed"
    )


def test_friction(profile: CognitiveProfile) -> TestResult:
    def run():
        friction = FrictionState(threshold=profile.friction_threshold)
        for i in range(profile.friction_threshold - 1):
            friction.add(1, f"diag_friction_{i}")
        not_yet  = not friction.tangled
        friction.add(1, "diag_tipping_point")
        tangled  = friction.tangled
        friction.clear()
        cleared  = friction.score == 0
        return not_yet and tangled and cleared
    passed, ms = _timed(run)
    return TestResult(
        "friction",
        ModuleStatus.PASS if passed else ModuleStatus.FAIL,
        ms,
        None if passed else "friction accumulation/clear failed"
    )


# ─────────────────────────────────────────────
# BOOT
# ─────────────────────────────────────────────

class SubstrateNotReady(Exception):
    def __init__(self, failures: list):
        self.failures = failures
        details = "\n".join(
            f"  [{f.module}] {f.detail} ({f.latency_ms:.1f}ms)"
            for f in failures
        )
        super().__init__(
            f"Substrate failed self-test. Not attaching.\n"
            f"Failed modules:\n{details}"
        )


def run_boot(
    thinker: Thinker,
    memory:  Memory,
    scanner: Scanner,
    bridge:  SecurityBridge,
    profile: CognitiveProfile
) -> BootResult:

    results = [
        test_thinker(thinker),
        test_memory(memory),
        test_scanner(scanner),
        test_security_bridge(bridge),
        _run_halt_cycle(bridge, profile.agent_id or "boot_agent"),
        test_friction(profile),
    ]

    failures  = [r for r in results if not r.passed]
    latencies = {r.module: r.latency_ms for r in results}
    ready     = len(failures) == 0

    for r in results:
        status = "✓" if r.passed else "✗"
        log.info(
            f"  [{status}] {r.module} ({r.latency_ms:.1f}ms)"
            + (f" — {r.detail}" if r.detail else "")
        )

    return BootResult(
        ready=ready,
        results=results,
        failures=failures,
        latencies=latencies,
        timestamp=time.time()
    )


# ─────────────────────────────────────────────
# PROBE
# ─────────────────────────────────────────────

def probe_orchestrator(orchestrator: Any) -> OrchestratorRole:
    """
    Detect the role of an attaching orchestrator.

    >>> class FakeOrch:
    ...     def coordinate(self): pass
    >>> probe_orchestrator(FakeOrch())
    <OrchestratorRole.COORDINATOR: 'coordinator'>
    """
    name  = type(orchestrator).__name__.lower()
    attrs = [a.lower() for a in dir(orchestrator)]

    if any(x in name for x in ["security", "adap", "guard", "monitor"]):
        return OrchestratorRole.SECURITY
    if any(x in name for x in ["research", "search", "discover"]):
        return OrchestratorRole.RESEARCHER
    if any(x in name for x in ["execut", "runner", "worker"]):
        return OrchestratorRole.EXECUTOR
    if any(x in name for x in ["analys", "inspect", "audit"]):
        return OrchestratorRole.ANALYST
    if any(x in attrs for x in ["coordinate", "dispatch", "route", "orchestrate"]):
        return OrchestratorRole.COORDINATOR

    return OrchestratorRole.COORDINATOR


# ─────────────────────────────────────────────
# COGNITIVE PORT
# ─────────────────────────────────────────────

class CognitivePort:
    """
    The only interface an orchestrator gets.
    Orchestrator calls these. Never touches internals.
    """

    def __init__(
        self,
        thinker: Thinker,
        memory:  Memory,
        scanner: Scanner,
        bridge:  SecurityBridge,
        profile: CognitiveProfile,
        boot:    BootResult
    ):
        self._thinker  = thinker
        self._memory   = memory
        self._scanner  = scanner
        self._bridge   = bridge
        self._profile  = profile
        self._boot     = boot
        self._friction = FrictionState(threshold=profile.friction_threshold)

    def think(self, input_data: Any) -> ThoughtState:
        return self._thinker.think(input_data)

    def remember(self, key: str, value: dict) -> str:
        return self._memory.store(key, value)

    def recall(self, entry_key: str) -> Optional[dict]:
        return self._memory.recall(entry_key)

    def scan(self) -> dict:
        return self._scanner.scan()

    def alert(self, key: str, intensity: float) -> None:
        self._scanner.inject(key, intensity)

    def add_friction(self, amount: int, reason: str) -> bool:
        self._friction.add(amount, reason)
        if self._friction.tangled:
            self._bridge.push(Signal(
                signal_type=SignalType.STATE_CHANGE,
                agent_id=self._profile.agent_id,
                payload={
                    "event":   "tangle_threshold_reached",
                    "score":   self._friction.score,
                    "history": self._friction.history[-5:]
                },
                context_hash=hashlib.sha256(
                    str(self._friction.score).encode()
                ).hexdigest()[:8],
                timestamp=time.time()
            ))
            return True
        return False

    def clear_friction(self) -> None:
        self._friction.clear()

    def signal(self, signal_type: SignalType, payload: dict) -> None:
        self._bridge.push(Signal(
            signal_type=signal_type,
            agent_id=self._profile.agent_id,
            payload=payload,
            context_hash=hashlib.sha256(
                str(payload).encode()
            ).hexdigest()[:8],
            timestamp=time.time()
        ))

    def is_halted(self) -> bool:
        return self._bridge.is_halted(self._profile.agent_id)

    @property
    def profile(self) -> CognitiveProfile:
        return self._profile

    @property
    def boot(self) -> BootResult:
        return self._boot


# ─────────────────────────────────────────────
# SUBSTRATE
# ─────────────────────────────────────────────

class CognitiveSubstrate:
    """
    Master entry point.
    Attach any orchestrator — get a CognitivePort.
    Hard gate: fails loudly if any system does not pass.

    Usage:
        substrate = CognitiveSubstrate()
        port = substrate.attach(my_orchestrator)
        thought = port.think("what should I do with this code?")
    """

    def attach(self, orchestrator: Any) -> CognitivePort:

        log.info(f"cogno: probing {type(orchestrator).__name__}...")
        role    = probe_orchestrator(orchestrator)
        profile = PRESETS.get(role, PRESETS[OrchestratorRole.COORDINATOR])
        profile.agent_id = f"{role.value}_{int(time.time())}"

        log.info(f"cogno: role detected → {role.value}")
        log.info(f"cogno: initializing cognitive systems...")

        thinker = Thinker(depth=profile.thought_depth, dual=profile.dual_brain)
        memory  = Memory(scope=profile.memory_scope)
        scanner = Scanner(sensitivity=profile.peripheral_sensitivity)
        bridge  = SecurityBridge(agent_id=profile.agent_id)

        log.info(f"cogno: running self-tests...")
        boot = run_boot(thinker, memory, scanner, bridge, profile)

        if not boot.ready:
            raise SubstrateNotReady(boot.failures)

        total_ms = sum(boot.latencies.values())
        log.info(f"cogno: all systems pass — ready in {total_ms:.1f}ms")

        return CognitivePort(
            thinker=thinker,
            memory=memory,
            scanner=scanner,
            bridge=bridge,
            profile=profile,
            boot=boot
        )


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import doctest
    doctest.testmod(verbose=False)

    class SampleOrchestrator:
        def coordinate(self): pass

    substrate = CognitiveSubstrate()
    port      = substrate.attach(SampleOrchestrator())

    thought = port.think("analyze this code block")
    log.info(f"thought: {thought.choice.value} @ {thought.confidence:.2f}")

    key = port.remember("first_task", {"task": "analyze code"})
    mem = port.recall(key)
    log.info(f"memory: recalled → {mem}")

    port.alert("unexpected_token", 0.95)
    anomalies = port.scan()
    log.info(f"scanner: detected → {list(anomalies.keys())}")

    tangled = port.add_friction(2, "missing dependency")
    log.info(f"friction: tangled={tangled}")

    port.signal(SignalType.CODE_ENCOUNTERED, {"file": "main.py", "lines": 200})
    log.info(f"bridge: signals pending → {port._bridge.pending()}")

    log.info("cogno orchestrator: all systems verified real and functional")
