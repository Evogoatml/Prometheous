# Prometheous Rebuild Plan

## Core Issues Identified

1. **Module Structure Broken**
   - `core/orchestrator.py` is a file, not a package, but code tries: `from core.orchestrator.polymorphic_swarm import ...`
   - `brain/` has both files and subdirectories with files, causing import confusion
   - Missing `__init__.py` files in key directories

2. **Circular Imports**
   - `core/gateway.py` imports `from core.orchestrator import orchestrator`
   - But `main.py` imports from both, creating cycles
   - `agents/` imports from `core/`, `core/` imports from `agents/`

3. **Scattered Compatibility Shims**
   - `core/orchestrator/polymorphic_swarm.py` - shim for non-existent submodule
   - `brain/loader.py` - re-exports from `brain/cognitive_loader.py`
   - Multiple fallback import patterns

4. **Location Issues**
   - `brain/agents/tool_agent.py` shouldn't be here
   - Brain should contain cognitive logic, not application agents
   - Too many modules at top level of `brain/`

## Correct Structure (Target)

```
Prometheous/
├── main.py                      # Entry point
├── config/                      # Configuration files
│   └── __init__.py
├── core/                        # Core system (keep as package)
│   ├── __init__.py
│   ├── gateway.py              # Main gateway
│   ├── orchestrator.py         # Orchestrator class (NOT a package)
│   ├── decision.py             # Decision engine
│   ├── mission/                # Mission package
│   │   ├── __init__.py
│   │   ├── conductor.py
│   │   └── frameworks.py
│   ├── mosaic/                 # Mosaic package
│   │   ├── __init__.py
│   │   └── polymorphic.py      # PolymorphicAgentSystem (move from conductor)
│   └── memory.py               # Conversation + knowledge base
├── brain/                      # Cognitive layer (core logic only)
│   ├── __init__.py
│   ├── cognitive_loader.py     # Hot-reload constraints
│   ├── cogno/                  # Deep cognitive substrate
│   │   ├── __init__.py
│   │   └── orchestrator.py
│   ├── si_orchestrator/        # SI system (keep as-is, internal)
│   │   ├── __init__.py
│   │   └── ... (SI internals)
│   └── knowledge_store.py      # Brain knowledge (for ability index)
├── swarm/                      # Agent swarm (package)
│   ├── __init__.py
│   ├── base.py                 # BaseAgent
│   ├── nodes.py                # Default nodes (scanner, etc.)
│   ├── orchestrator.py         # SwarmOrchestrator
│   ├── telegram.py             # TelegramAgent
│   └── bridge.py               # Telegram bridge utilities
├── agents/                     # Application agents (package)
│   ├── __init__.py
│   ├── scanner.py
│   ├── paradox.py
│   ├── task_agent.py
│   ├── web_search_agent.py
│   ├── growth_agent.py
│   ├── learn_agent.py
│   ├── knowledge_agent.py
│   ├── matrix_agent.py
│   ├── ghost_sentinel_agent.py
│   ├── shopify_ads_agent.py
│   ├── mcp_tool_agent.py
│   ├── mosaic_agent.py
│   ├── mission_agent.py
│   └── cogno_adapter.py
├── llm/                        # LLM backends (package)
│   ├── __init__.py
│   ├── client.py              # Main LLM client
│   ├── backends.py            # OpenAI, Grok, Ollama
│   ├── tool_router.py         # Tool execution
│   └── conversation.py        # Chat history
├── bus/                        # Event bus (package)
│   ├── __init__.py
│   └── agent_bus.py           # Pub/sub
├── controllers/                # Controller facade (package)
│   ├── __init__.py
│   ├── memory.py
│   ├── tools.py
│   └── llm.py
├── genesis/                    # Boot validation (package)
│   ├── __init__.py
│   └── engine.py
├── tools/                      # Integration tools (package)
│   ├── __init__.py
│   ├── github_loader.py
│   └── ...
├── memory/                     # Memory systems (package)
│   ├── __init__.py
│   └── ...
├── knowledge/                  # Knowledge systems (package)
│   ├── __init__.py
│   └── ...
├── learning/                   # Learning systems (package)
│   ├── __init__.py
│   └── ...
├── paradox/                    # Paradox detection (package)
│   ├── __init__.py
│   └── ...
├── ghost_sentinel/             # Security mesh (package)
│   ├── __init__.py
│   └── ...
├── growth/                     # Ad automation (package)
│   ├── __init__.py
│   └── ...
├── matrix/                     # NeuroMatrix (package)
│   ├── __init__.py
│   └── ...
├── rag/                        # RAG (package)
│   ├── __init__.py
│   └── ...
├── utils/                      # Utilities (package)
│   ├── __init__.py
│   ├── config.py
│   └── helpers.py
└── ... (other subdirs as packages)
```

## Phase 1: Fix Core Imports

1. ✅ Convert all directories to Python packages with `__init__.py`
2. ✅ Fix `core/orchestrator.py` - it's a module, add compatibility exports at top
3. ✅ Remove misplaced compatibility shims
4. ✅ Clean circular imports between `core/` and `agents/`
5. ✅ Add explicit `__all__` exports to all modules

## Phase 2: Fix Import Patterns

- All `from core.X` should work (X = module or subpackage)
- All `from brain.X` should work
- All `from agents.X` should work
- No relative imports between top-level packages

## Phase 3: Test Import Chain

```python
# Should all work without error:
from main import bootstrap, handle
from core.gateway import gateway
from core.orchestrator import orchestrator
from swarm.base import BaseAgent
from agents.scanner import ScannerAgent
from brain.cognitive_loader import CognitiveLoader
from llm.client import llm
from bus.agent_bus import bus
```

---

## Next Step

Run rebuild script to:
1. Create all missing `__init__.py` files
2. Fix import statements in all files
3. Remove/consolidate shims
4. Add dependency injection to break cycles
