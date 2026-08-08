# SI Orchestrator (Prometheous) — Phase 1 MVP

**Synthetic Intelligence Orchestrator**: modular, extensible design for memory recall and learning.

Lives at:

```text
/home/popi/Prometheous/work1/si_orchestrator/
```

## Design principles (implemented)

| Principle | How |
|-----------|-----|
| Component-based | `core/`, `memory/`, `learning/`, `symbolic/`, `agents/` |
| Plugin / registry | `core/registry.py` + `config/default.json` |
| Interface contracts | ABCs in `core/interfaces.py` + JSON schema |
| Versioning | `schema_version: 1.0.0` on records & config |
| Dependency injection | `bootstrap.build_orchestrator()` wires implementations |

## Layout

```text
si_orchestrator/
├── core/           # orchestrator, registry, interfaces
├── memory/         # JsonMemoryBackend, HopfieldMemoryBackend (Py MVP)
├── learning/       # ReplayLearningStrategy
├── symbolic/       # RuleSymbolicReasoner (Lisp bridge later)
├── agents/         # PrometheusAgent, EchoAgent
├── config/         # default.json + schemas
├── utils/
├── rust_extensions/  # Cargo stub for Phase 2 Hopfield
├── tests/
└── data/           # runtime memory store
```

## Run

```bash
cd /home/popi/Prometheous/work1
python3 -m si_orchestrator "Who are you Prometheus?"
python3 -m si_orchestrator --repl
python3 -m si_orchestrator --status
python3 si_orchestrator/tests/test_si_mvp.py
```

## Key interfaces

- `MemoryBackend` — `store` / `recall` / `delete` / `consolidate`
- `LearningStrategy` — `observe` / `improve`
- `SymbolicReasoner` — `assert_rule` / `query`
- `Agent` — `run(AgentTask) -> AgentResult`

## Relation to existing Prometheous package

| Existing (`Prometheous/…`) | SI layer |
|----------------------------|----------|
| `core/orchestrator.py` (swarm dispatch) | `si_orchestrator` (SI cycle + memory/learning) |
| `core/memory.py` (chat/KB) | pluggable `MemoryBackend` |
| `main.py` LLM phrase gateway | optional later; SI owns decisions |

Phase 1 does **not** delete legacy code — it adds a clean spine you can grow.

## Roadmap

1. **Phase 1 (done)** — MVP orchestrator, JSON + Hopfield-Py memory, replay learning, rules, Prometheus agent  
2. **Phase 2** — Rust Hopfield via PyO3, async consolidation, richer recall  
3. **Phase 3** — self-evolution hooks, multi-backend hybrid, distributed scaling  
