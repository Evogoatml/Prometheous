# Prometheous

**Single-LLM Gateway Architecture** — A rule-based multi-agent system where one LLM only phrases responses; all decisions, routing, and actions are deterministic code.

> **Philosophy**: The LLM is a translator, not a decision-maker. The system decides; the LLM speaks.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Telegram Bot                         │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                      Core Gateway                            │
│  (core/gateway.py) — intent parsing → decision → dispatch   │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Core Orchestrator                         │
│  (core/orchestrator.py) — task lifecycle, agent registry    │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌───────────────┐ ┌───────────┐ ┌───────────────┐
│  Swarm Agent  │ │ Swarm Orb │ │  Tile Agents  │
│  (swarm/)     │ │ (swarm/)  │ │ (tiles/)      │
└───────────────┘ └───────────┘ └───────────────┘
        │              │              │
        ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Cognitive Layer                            │
│  brain/cognitive_loader.py — hot-reloadable YAML constraints │
│  brain/cogno/ — deep cognitive substrate                     │
│  brain/si_orchestrator/ — symbolic reasoning, learning       │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Principles

| Principle | Implementation |
|-----------|----------------|
| **No LLM decisions** | Rule-based intent parsing (`core/decision.py`) |
| **Single LLM gateway** | `llm/client.py` — only phrases replies |
| **Hot-reloadable cognition** | YAML constraints in `config/cognitive_config.yaml` |
| **Mandatory Telegram** | Bot auto-starts on boot; no degraded mode |
| **Agent swarm** | Register → dispatch → execute via `swarm/orchestrator.py` |
| **Genesis validation** | Boot-time health checks (`genesis/engine.py`) |

---

## Quick Start

### Prerequisites
- Python 3.11+
- Telegram Bot Token (from @BotFather)
- Telegram Chat ID
- Optional: OpenAI/Grok/Ollama API keys for LLM replies

### Install
```bash
git clone https://github.com/Evogoatml/Prometheous.git
cd Prometheous
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure
```bash
cp .env.example .env
nano .env  # Add your keys
```

Required in `.env`:
```bash
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=123456789
# Optional LLM (for natural replies)
OPENAI_API_KEY=sk-...         # or GROK_API_KEY, or use Ollama
PROM_LLM_MODEL=gpt-4o-mini
PROM_TELEGRAM_LLM=1
```

### Run
```bash
# Full system (Telegram + REPL)
python main.py

# Daemon only (no REPL)
python main.py --no-repl
# or: PROM_REPL=0 python main.py
```

---

## Agents

| Agent | Module | Purpose |
|-------|--------|---------|
| `scanner` | `agents/scanner.py` | Network/vulnerability scanning |
| `paradox` | `agents/paradox.py` | Paradox detection & audit |
| `telegram` | `swarm/telegram.py` | Telegram bot interface |
| `github_loader` | `tools/github_loader.py` | GitHub repo ingestion |
| `cogno` | `agents/cogno_adapter.py` | Cognitive substrate bridge |
| `matrix` | `agents/matrix_agent.py` | NeuroMatrix operations |
| `knowledge` | `agents/knowledge_agent.py` | Knowledge graph queries |
| `ghost_sentinel` | `agents/ghost_sentinel_agent.py` | Adaptive CRDT security mesh |
| `web_search` | `agents/web_search_agent.py` | Web search & retrieval |
| `shopify_ads` | `agents/shopify_ads_agent.py` | Meta/Shopify ad orchestration |
| `task` | `agents/task_agent.py` | Task decomposition & execution |
| `growth` | `agents/growth_agent.py` | Growth campaign automation |
| `learn` | `agents/learn_agent.py` | Continuous learning loops |
| `mcp_tools` | `agents/mcp_tool_agent.py` | MCP tool server bridge |
| `mosaic` | `agents/mosaic_agent.py` | Multi-agent blackboard |
| `mission` | `agents/mission_agent.py` | Mission planning & fleets |

### Swarm Built-ins (auto-registered)
`recon`, `exploit`, `privesc`, `persistence`, `pivot`, `exfil`, `report` — pentest workflow agents

### Tiles (specialist modules)
Auto-discovered from `tiles/registry.py` — wrapped as agents

---

## Subsystems

### Cognitive Layer (`brain/`)
- **CognitiveLoader** — Hot-reloadable YAML constraints per role
- **Cogno** — Deep cognitive substrate (entanglement, bitstate, crypto)
- **SI Orchestrator** — Symbolic reasoning, learning, memory, Rust extensions

### Kernel (`kernel/`)
- **ReactEngine** — Reasoning/acting loop
- **NeuroReactEngine** — Neural-enhanced react loop
- **Interpreter** — DSL execution
- **ServiceRegistry** — Dependency injection

### Knowledge (`knowledge/`)
- **KnowledgeSystem** — Dual-brain (symbolic + neural)
- **SkillDiscovery** — Automatic capability extraction
- **AbilityIndex** — Searchable skill catalog
- **TransferMapper** — Cross-domain knowledge transfer

### Learning (`learning/`)
- **Optimizer** — Online parameter tuning
- **Trajectory** — Execution trace recording
- **TaskMemory** — Episodic task storage
- **Awareness** — Meta-cognitive monitoring
- **Healing** — Self-repair via patch proposals

### Mosaic (`core/mosaic/`)
- **PolymorphicAgentSystem** — Dynamic agent composition
- **Blackboard** — Shared workspace
- **Tiles** — Composable specialists

### Mission (`core/mission/`)
- **Conductor** — Multi-phase mission orchestration
- **Fleet** — Agent fleet management
- **Frameworks** — Reusable workflow templates

### Ghost Sentinel (`ghost_sentinel/`)
- **Adaptive CRDT** — Conflict-free replicated state
- **Policy CRDT** — Distributed policy enforcement
- **Transport** — Encrypted mesh networking
- **MCP Codec** — Model Context Protocol encoding

### Growth (`growth/ads/`)
- **MetaClient** — Facebook/Instagram Ads API
- **ShopifyClient** — E-commerce integration
- **Orchestrator** — Campaign automation
- **Planner** — Budget/allocation strategy

---

## Configuration

### Cognitive Constraints (`config/cognitive_config.yaml`)
```yaml
roles:
  scanner:
    constraints:
      - "Never execute exploits without confirmation"
      - "Log all scan targets"
    superprompt: "You are a precise vulnerability scanner..."
  paradox:
    constraints:
      - "Audit all decisions for contradictions"
    superprompt: "You are a paradox auditor..."
```

Reload at runtime:
```python
from brain.cognitive_loader import CognitiveLoader
cog = CognitiveLoader()
cog.load("config/cognitive_config.yaml")  # hot-reload
```

### Genesis Validation (`genesis/engine.py`)
Boot-time checks:
- Python version
- Core dependencies
- Memory modules
- State integrity
- System resources (disk, RAM)

---

## LLM Backends

| Backend | Env Vars | Use Case |
|---------|----------|----------|
| OpenAI | `OPENAI_API_KEY`, `PROM_LLM_MODEL` | Default cloud |
| Grok/xAI | `GROK_API_KEY`, `PROM_LLM_MODEL=grok-2` | Alternative cloud |
| Ollama | `OLLAMA_URL`, `OLLAMA_MODEL` | Local/offline |

Only used when `PROM_TELEGRAM_LLM=1`. System works fully without LLM (fallback formatter).

---

## Project Structure

```
Prometheous/
├── main.py                 # Entry point — full bootstrap
├── config/                 # YAML cognitive configs
├── agents/                 # App-layer agents
├── swarm/                  # Swarm orchestration & nodes
├── core/                   # Gateway, orchestrator, decision, mission, mosaic
├── brain/                  # Cognitive layer (cogno, si_orchestrator, loader)
├── kernel/                 # React engines, interpreter, service registry
├── knowledge/              # Knowledge systems, skill discovery
├── learning/               # Optimizer, trajectory, healing, awareness
├── memory/                 # GraphRAG, quantum graph, vault, conversations
├── controllers/            # Memory, tools, LLM controllers
├── llm/                    # Client, backends, conversation, tool router
├── tiles/                  # Specialist tile modules
├── bus/                    # Agent message bus (pub/sub)
├── paradox/                # Paradox detection
├── genesis/                # Boot validation
├── mcp/                    # Model Context Protocol server
├── matrix/                 # NeuroMatrix substrate
├── vortex/                 # Vortex agent, indexing, memory, superprompt
├── ghost_sentinel/         # Adaptive security mesh
├── growth/                 # Ads orchestration
├── tools/                  # GitHub, web search, HuggingFace, Google
├── rag/                    # Retrieval-augmented generation
├── webhook/                # Telegram webhook handler
└── utils/                  # Config, helpers, state
```

---

## Development

### Add a New Agent
```python
# agents/my_agent.py
from swarm.base import BaseAgent

class MyAgent(BaseAgent):
    name = "my_agent"
    role = "My Specialist"
    specialty = "Does something useful"
    
    def execute(self, payload):
        # Your logic here
        return {"status": "ok", "result": "done"}

# Register in main.py bootstrap()
```

### Add Cognitive Constraints
Edit `config/cognitive_config.yaml` — reloads automatically.

### Run Tests
```bash
python -m pytest tests/ -v
# or integration test
PROM_IT_PROBE=true python main.py
```

---

## Deployment

### systemd Service
```ini
# /etc/systemd/system/prometheous.service
[Unit]
Description=Prometheous Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=prometheous
WorkingDirectory=/opt/Prometheous
ExecStart=/opt/Prometheous/.venv/bin/python main.py --no-repl
Restart=always
RestartSec=10
EnvironmentFile=/opt/Prometheous/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now prometheous
```

### Docker
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py", "--no-repl"]
```

```bash
docker build -t prometheous .
docker run -d --restart unless-stopped --env-file .env prometheous
```

---

## License

MIT License — see [LICENSE](LICENSE)

---

## Status

**Active development** — Core architecture stable, new agents/subsystems added regularly.

Key milestones:
- ✅ Single-LLM gateway architecture
- ✅ Rule-based decision engine
- ✅ Hot-reloadable cognitive constraints
- ✅ Telegram bot with mandatory auto-start
- ✅ Swarm orchestration (core + swarm.orb)
- ✅ Genesis boot validation
- ✅ Cogno cognitive substrate
- ✅ SI Orchestrator (symbolic reasoning)
- ✅ Mosaic multi-agent blackboard
- ✅ Mission/fleet orchestration
- ✅ Ghost Sentinel adaptive mesh
- ✅ Growth ads automation
- ✅ Knowledge system with skill discovery
- ✅ Learning loops with self-healing

---

**Built for autonomous, auditable, portable agent swarms.**