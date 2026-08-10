#!/usr/bin/env python3
"""
Prometheous — single-LLM gateway.

One LLM, used ONLY to phrase natural-language replies to the user.
All decisions are rule-based. The LLM never decides or acts on its own.
"""
from __future__ import annotations

import os
import sys
import logging
import time
import importlib
from pathlib import Path

# Make project root importable when run from anywhere.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env very early (API keys like TELEGRAM_BOT_TOKEN, GROK_API_KEY live here).
# Always load from the project root so it works regardless of the cwd.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    # Fallback: parse .env manually if python-dotenv isn't installed.
    try:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Telegram is mandatory: fail fast instead of silent degraded mode.
if not os.getenv("TELEGRAM_BOT_TOKEN"):
    print("[main] FAIL: TELEGRAM_BOT_TOKEN is required.")
    print("  Add it to .env in this directory and restart.")
    sys.exit(2)

from core.gateway import gateway, maybe_index_rag
from core.orchestrator import orchestrator
from swarm.nodes import DEFAULT_NODES

# Lightweight app-layer agents (always loaded when main.py runs).
from agents.scanner import ScannerAgent
from agents.paradox import ParadoxAgent  # brain/paradox integration point

# More agents from the structured files (now wired to be used)
try:
    from swarm.telegram import TelegramAgent
except Exception:
    TelegramAgent = None

try:
    from tools.github_loader import GitHubLoaderAgent
except Exception:
    GitHubLoaderAgent = None

try:
    from agents.cogno_adapter import CognoAgent
except Exception:
    CognoAgent = None

try:
    from agents.matrix_agent import MatrixAgent
except Exception:
    MatrixAgent = None

try:
    from agents.knowledge_agent import KnowledgeAgent
except Exception:
    KnowledgeAgent = None

try:
    from agents.ghost_sentinel_agent import GhostSentinelAgent
except Exception:
    GhostSentinelAgent = None

try:
    from agents.web_search_agent import WebSearchAgent
except Exception:
    WebSearchAgent = None

try:
    from agents.shopify_ads_agent import ShopifyAdsAgent
except Exception:
    ShopifyAdsAgent = None

try:
    from agents.task_agent import TaskAgent
except Exception:
    TaskAgent = None

try:
    from agents.growth_agent import GrowthAgent
except Exception:
    GrowthAgent = None

try:
    from agents.learn_agent import LearnAgent
except Exception:
    LearnAgent = None

try:
    from agents.mcp_tool_agent import McpToolsAgent
except Exception:
    McpToolsAgent = None

try:
    from agents.mosaic_agent import MosaicAgent
except Exception:
    MosaicAgent = None

try:
    from agents.mission_agent import MissionAgent
except Exception:
    MissionAgent = None

# Import additional dormant modules so their code is loaded/used
try:
    import agents.neuro_swarm
    import agents.integration_test
    import agents.swarm_orchestrator
    import swarm.orchestrator
    import swarm.telegram  # already have class
except Exception:
    pass

try:
    import bus.knowledge_system
    import core.orchestrator.polymorphic_swarm
except Exception:
    pass

try:
    import importlib
    importlib.import_module("llm.intent_parser")
    importlib.import_module("llm.mcp_client")
except Exception:
    pass

# Genesis (boot validation from structured files)
try:
    from genesis.engine import GenesisEngine
    from utils.state import state as genesis_state
    _genesis = GenesisEngine(genesis_state)
except Exception:
    _genesis = None

# Structured components (moved-in, now wired)
from bus.agent_bus import bus
from controllers import memory, tools, llm as ctrl_llm  # controllers facade
from brain.cognitive_loader import CognitiveLoader

# Tiles (specialist modules)
try:
    from tiles.registry import TileRegistry
    _tile_registry = TileRegistry()
except Exception:
    _tile_registry = None


def bootstrap() -> None:
    """Register default agents with the orchestrators.
    Also loads cognitive, bus, controllers as part of assembling the structure.
    """
    # 1. Cognitive (hot-reloadable) - load early once
    try:
        cog = CognitiveLoader()
        cog.load("config/cognitive_config.yaml")
        print("[bootstrap] CognitiveLoader active (hot-reloadable constraints)")
    except Exception as e:
        print("[bootstrap] CognitiveLoader skipped (no config or error):", e)

    maybe_index_rag()

    # 2. Register swarm built-ins
    for node_cls in DEFAULT_NODES:
        orchestrator.register_agent(node_cls.name, node_cls())

    # 3. Register lightweight agents that ship with the project
    for cls in (
        ScannerAgent,
        ParadoxAgent,
        TelegramAgent,
        GitHubLoaderAgent,
        CognoAgent,
        MatrixAgent,
        KnowledgeAgent,
        GhostSentinelAgent,
        WebSearchAgent,
        ShopifyAdsAgent,
        TaskAgent,
        LearnAgent,
        GrowthAgent,
        McpToolsAgent,
        MosaicAgent,
        MissionAgent,
    ):
        if cls is None:
            continue
        try:
            orchestrator.register_agent(cls.name, cls())
        except Exception as exc:
            print(f"[bootstrap] agent registration skipped: {cls.__name__}: {exc}")

    # 5. Ensure swarm.orb agents are also fetchable from core.orchestrator
    try:
        from swarm.orchestrator import orb as swarm_orb
        swarm_agents = getattr(swarm_orb, 'agents', None) or {}
        for name, ag in list(swarm_agents.items()):
            try:
                if orchestrator.get_agent(name) is None:
                    orchestrator.register_agent(name, ag)
            except Exception as exc:
                print(f"[bootstrap] swarm->core bridge failed: {name}: {exc}")
    except Exception as exc:
        print(f"[bootstrap] swarm bridge unavailable:", str(exc)[:80])

    # Auto-start Telegram bot (mandatory).
    try:
        tg = orchestrator.get_agent("telegram")
        if tg is None:
            print("[bootstrap] Telegram agent not registered.")
            sys.exit(2)
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        missing = []
        if not token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        if missing:
            print("[bootstrap] FAIL: Telegram requires:", ", ".join(missing))
            print("  Add them to .env in this directory and restart.")
            sys.exit(2)

        # Test hook: if PROM_IT_PROBE is set, do not start polling and write a probe marker file.
        if os.getenv("PROM_IT_PROBE") == "true":
            print("[bootstrap] PROM_IT_PROBE=true — Telegram auto-start skipped for integration test")
            try:
                Path("/tmp/prometheus_it_probe").write_text("ok", encoding="utf-8")
            except Exception:
                pass
        else:
            tg.execute({"mode": "start", "poll_interval": 2})
            print("[bootstrap] Telegram bot auto-started")
    except Exception as e:
        print("[bootstrap] Telegram mandatory start failed:", e)
        sys.exit(2)

    # 4. Bus + controllers available globally for agents to use
    # (agents can import from bus.agent_bus import bus  or from controllers)
    # attach for convenience
    orchestrator.bus = bus
    orchestrator.controllers = {"memory": memory, "tools": tools, "llm": ctrl_llm}
    print("[bootstrap] Bus and controllers loaded + attached to orchestrator")

    # 5. Register tiles as agents (wrapped for sync execute contract)
    if _tile_registry:
        from swarm.base import BaseAgent
        for tname in _tile_registry.list():
            tile_obj = _tile_registry.get(tname)
            class _TileAgent(BaseAgent):
                name = tname
                role = tname.title()
                specialty = "tile specialist"
                _tile = tile_obj
                def execute(self, payload):
                    self.tasks_completed += 1
                    try:
                        import asyncio
                        task_arg = {"task": payload.get("user_msg", payload)}
                        if asyncio.iscoroutinefunction(self._tile.execute):
                            coro = self._tile.execute(task_arg)
                            try:
                                loop = asyncio.get_running_loop()
                            except RuntimeError:
                                loop = None
                            if loop and loop.is_running():
                                res = {"status": "async_tile", "note": "run under async context"}
                            else:
                                res = asyncio.run(coro)
                        else:
                            res = self._tile.execute(task_arg)
                        return {"status": "ok", "tile": self.name, "result": res}
                    except Exception as ex:
                        return {"status": "ok", "tile": self.name, "result": {"error": str(ex)}}
            try:
                orchestrator.register_agent(tname, _TileAgent())
            except Exception:
                pass
        print("[bootstrap] Tiles registered as agents:", _tile_registry.list())

    # 6. Run Genesis (structured boot validation) — now wired
    if _genesis:
        try:
            import asyncio
            passed = asyncio.run(_genesis.run())
            if not passed:
                print("[bootstrap][GENESIS] Some checks failed — system continuing (dev mode)")
            else:
                print("[bootstrap][GENESIS] All checks passed")
        except Exception as ge:
            print("[bootstrap][GENESIS] Skipped due to error:", ge)

    # 7. Real Cogno substrate attach (the intended way from brain/cogno)
    try:
        from brain.cogno.orchestrator import CognitiveSubstrate
        sub = CognitiveSubstrate()
        port = sub.attach(orchestrator)
        orchestrator.cogno_port = port
        print("[bootstrap] Cogno substrate attached via .attach() — deep cognitive layer active")
    except Exception as e:
        orchestrator.cogno_port = None
        print("[bootstrap] Cogno attach (real integration):", str(e)[:120])

    # 8. Advanced KnowledgeSystem (from moved knowledge/) now usable thanks to shims
    try:
        from knowledge.knowledge_system import KnowledgeSystem as AdvKS
        orchestrator.adv_knowledge = AdvKS()
        print("[bootstrap] Prometheous symbolic KnowledgeSystem attached")
    except Exception as e:
        print("[bootstrap] Adv knowledge:", str(e)[:80])

    # 8b. Brain knowledge — always ready on start (build index if missing)
    try:
        from brain.knowledge_store import brain_knowledge
        from brain.build_ability_knowledge import TRAINING

        stats = brain_knowledge.load()
        if (not stats.get("online") or int(stats.get("count") or 0) == 0) and TRAINING.is_dir():
            print("[bootstrap] Brain knowledge empty — building full index on start…")
            from brain.build_ability_knowledge import build as build_brain

            build_brain()
            stats = brain_knowledge.load(force=True)
        orchestrator.brain_knowledge = brain_knowledge
        print(f"[bootstrap] Brain knowledge ON — {stats.get('count', 0)} docs")
    except Exception as e:
        print("[bootstrap] Brain knowledge:", str(e)[:120])

    # 9. NeuroMatrix substrate
    try:
        from matrix.matrix import NeuroMatrix

        orchestrator.neuro_matrix = NeuroMatrix()
        print("[bootstrap] NeuroMatrix attached")
    except Exception as e:
        orchestrator.neuro_matrix = None
        print("[bootstrap] NeuroMatrix:", str(e)[:120])

    # 10. Mosaic + mission + frameworks — full stack, always
    try:
        from core.mosaic import PolymorphicAgentSystem, get_mosaic

        orchestrator.polymorphic = PolymorphicAgentSystem()
        orchestrator.mosaic = get_mosaic()
        if orchestrator.get_agent("mosaic") is None and MosaicAgent is not None:
            orchestrator.register_agent("mosaic", MosaicAgent())
        print("[bootstrap] Mosaic online")
    except Exception as e:
        print("[bootstrap] Mosaic:", str(e)[:120])

    try:
        from core.mission import get_conductor

        orchestrator.mission = get_conductor()
        if orchestrator.get_agent("mission") is None and MissionAgent is not None:
            orchestrator.register_agent("mission", MissionAgent())
        print("[bootstrap] Mission conductor online")
    except Exception as e:
        print("[bootstrap] Mission:", str(e)[:120])

    try:
        from core.mission.frameworks import ensure_framework_agents

        fw = ensure_framework_agents()
        names = [k for k, v in fw.items() if not isinstance(v, dict)]
        print(f"[bootstrap] Frameworks online: {', '.join(names)}")
    except Exception as e:
        print("[bootstrap] Frameworks:", str(e)[:120])

    # 11. Ghost Sentinel
    try:
        gs = orchestrator.get_agent("ghost_sentinel")
        if gs is not None:
            orchestrator.ghost_sentinel = gs
            print("[bootstrap] Ghost Sentinel active")
    except Exception as e:
        print("[bootstrap] Ghost Sentinel:", str(e)[:120])


    # 12. Architecture enhancements bootstrap
    try:
        from core.planning import HierarchicalPlanner
        orchestrator.planner = HierarchicalPlanner()
        print("[bootstrap] HierarchicalPlanner online")
    except Exception as e:
        print(f"[bootstrap] HierarchicalPlanner: {str(e)[:80]}")
    
    try:
        from core.verification import VerificationLayer
        orchestrator.verifier = VerificationLayer()
        print("[bootstrap] VerificationLayer online")
    except Exception as e:
        print(f"[bootstrap] VerificationLayer: {str(e)[:80]}")
    
    try:
        from core.reasoning import ReasoningRecorder
        orchestrator.reasoning = ReasoningRecorder()
        print("[bootstrap] ReasoningRecorder online")
    except Exception as e:
        print(f"[bootstrap] ReasoningRecorder: {str(e)[:80]}")
    
    try:
        from core.constraints import ConstraintSolver
        orchestrator.constraint_solver = ConstraintSolver()
        print("[bootstrap] ConstraintSolver online")
    except Exception as e:
        print(f"[bootstrap] ConstraintSolver: {str(e)[:80]}")
    
    try:
        from core.consensus import AgentConsensus
        orchestrator.consensus = AgentConsensus()
        print("[bootstrap] AgentConsensus online")
    except Exception as e:
        print(f"[bootstrap] AgentConsensus: {str(e)[:80]}")
    
    try:
        from learning.continuous_improver import ContinuousImprover
        orchestrator.improver = ContinuousImprover()
        print("[bootstrap] ContinuousImprover online")
    except Exception as e:
        print(f"[bootstrap] ContinuousImprover: {str(e)[:80]}")
    
    try:
        from core.world_model import WorldModel
        orchestrator.world_model = WorldModel()
        print("[bootstrap] WorldModel online")
    except Exception as e:
        print(f"[bootstrap] WorldModel: {str(e)[:80]}")
    
    try:
        from agents.skill_composer import SkillComposer
        orchestrator.skill_composer = SkillComposer()
        print("[bootstrap] SkillComposer online")
    except Exception as e:
        print(f"[bootstrap] SkillComposer: {str(e)[:80]}")
    
    try:
        from core.testing import AdversarialTester
        orchestrator.adversarial_tester = AdversarialTester()
        print("[bootstrap] AdversarialTester online")
    except Exception as e:
        print(f"[bootstrap] AdversarialTester: {str(e)[:80]}")
    
    try:
        from core.budget import BudgetController
        orchestrator.budget = BudgetController()
        print("[bootstrap] BudgetController online")
    except Exception as e:
        print(f"[bootstrap] BudgetController: {str(e)[:80]}")
    
    try:
        from core.observability import Telemetry
        orchestrator.telemetry = Telemetry()
        print("[bootstrap] Telemetry online")
    except Exception as e:
        print(f"[bootstrap] Telemetry: {str(e)[:80]}")
    
    try:
        from core.self_aware_orchestrator import MetaReasoningEngine
        orchestrator.meta_reasoner = MetaReasoningEngine()
        print("[bootstrap] MetaReasoningEngine online")
    except Exception as e:
        print(f"[bootstrap] MetaReasoningEngine: {str(e)[:80]}")
    
    try:
        from core.feedback import FeedbackLoop
        orchestrator.feedback = FeedbackLoop()
        print("[bootstrap] FeedbackLoop online")
    except Exception as e:
        print(f"[bootstrap] FeedbackLoop: {str(e)[:80]}")
    
    try:
        from core.mosaic.parallel import DAGExecutor
        orchestrator.dag_executor = DAGExecutor()
        print("[bootstrap] DAGExecutor (parallel mosaic) online")
    except Exception as e:
        print(f"[bootstrap] DAGExecutor: {str(e)[:80]}")

    print("[bootstrap] FULL SYSTEM READY — agents:", ", ".join(sorted(orchestrator.list_agents())))


def handle(text: str, chat_id: int = 0) -> str:
    """Process a user message via the shared gateway."""
    text = text.strip()
    if not text:
        return ""
    result = gateway.handle(text, context={"channel": "repl", "chat_id": chat_id})
    return result.reply or ""


def start() -> None:
    """One start: full bootstrap + Telegram. Entire system. No partial modes."""
    bootstrap()
    print("[main] Prometheous running — full stack.")
    print("[main] Agents:", ", ".join(sorted(orchestrator.list_agents())))
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        print("\n[main] Shutting down.")


# Back-compat names (both = full start)
daemon = start
repl = start


if __name__ == "__main__":
    start()
