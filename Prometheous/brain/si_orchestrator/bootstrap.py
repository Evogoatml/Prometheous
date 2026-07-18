"""
Build a fully wired SIOrchestrator from config (dependency injection).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .agents import EchoAgent, ExecutorAgent, NavigatorAgent, PrometheusAgent, ToolAgent
from .config.loader import load_config
from .core.orchestrator import SIOrchestrator
from .core.registry import Registry
from .learning import LearningCoordinator, ReplayLearningStrategy
from .memory import HopfieldMemoryBackend, HybridMemoryBackend, JsonMemoryBackend
from .symbolic import LyspBridge, RuleSymbolicReasoner
from .utils.logging import setup_logging


def build_orchestrator(
    config_path: str | Path | None = None,
    *,
    base_dir: str | Path | None = None,
) -> SIOrchestrator:
    cfg = load_config(config_path)
    setup_logging(cfg.get("system", {}).get("log_level", "INFO"))

    root = Path(base_dir) if base_dir else Path(__file__).resolve().parent
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Load last trained tuning weights (no-op if missing)
    try:
        from .learning.tuning_state import load_tuning, set_active_tuning

        set_active_tuning(load_tuning(root / "data" / "tuning.json"))
    except Exception:
        pass

    reg = Registry()

    # Prefer explicit Python wiring for MVP reliability; plugins optional.
    json_path = root / cfg.get("memory", {}).get("json_path", "data/memory_store.json")
    if not json_path.is_absolute():
        json_path = root / json_path
    dim = int(cfg.get("memory", {}).get("hopfield_dim", 64))

    # Dual-brain hybrid is the default long-term+associative fabric
    hybrid = HybridMemoryBackend(json_path=json_path, hopfield_dim=dim)
    reg.register_memory(hybrid, name="default")
    reg.register_memory(JsonMemoryBackend(path=json_path), name="json")
    reg.register_memory(HopfieldMemoryBackend(dim=dim), name="hopfield")
    reg.register_memory(hybrid, name="hybrid")

    strategy = ReplayLearningStrategy(
        capacity=int(cfg.get("learning", {}).get("capacity", 256))
    )
    reg.register_learning(strategy, name="default")
    # coordinator is attachable; not a registry type yet
    reg._learning_coordinator = LearningCoordinator(  # type: ignore[attr-defined]
        strategy, memory=hybrid
    )

    reg.register_symbolic(LyspBridge(fallback=RuleSymbolicReasoner()), name="default")
    reg.register_symbolic(RuleSymbolicReasoner(), name="rules")
    reg.register_agent(PrometheusAgent(), name="prometheus")
    reg.register_agent(EchoAgent(), name="echo")
    # Sandbox tools: Prometheous tree + si workspace + optional convo/adaptive_crypto only
    reg.register_agent(ToolAgent(), name="tools")
    reg.register_agent(ExecutorAgent(), name="executor")
    reg.register_agent(NavigatorAgent(), name="navigator")

    defaults = cfg.get("defaults") or {}
    return SIOrchestrator(
        reg,
        default_memory=defaults.get("memory", "default"),
        default_learning=defaults.get("learning", "default"),
        default_symbolic=defaults.get("symbolic", "default"),
        default_agent=defaults.get("agent", "prometheus"),
    )


def build_from_plugins(config_path: str | Path | None = None) -> SIOrchestrator:
    """Alternate bootstrap: pure registry.load_from_config (for extension demos)."""
    cfg = load_config(config_path)
    setup_logging(cfg.get("system", {}).get("log_level", "INFO"))
    reg = Registry()
    # fix relative paths in plugin args for json memory
    plugins = cfg.get("plugins") or {}
    root = Path(__file__).resolve().parent
    for item in plugins.get("memory") or []:
        args = item.get("args") or {}
        if "path" in args and not Path(args["path"]).is_absolute():
            args["path"] = str(root / args["path"])
            item["args"] = args
    reg.load_from_config(plugins)
    defaults = cfg.get("defaults") or {}
    return SIOrchestrator(
        reg,
        default_memory=defaults.get("memory", "default"),
        default_learning=defaults.get("learning", "default"),
        default_symbolic=defaults.get("symbolic", "default"),
        default_agent=defaults.get("agent", "prometheus"),
    )
