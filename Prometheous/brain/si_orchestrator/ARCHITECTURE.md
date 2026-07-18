# Prometheous SI — Architecture Alignment

This document maps the **polyglot SI design** (from your other-agent sessions)
onto the code under `work1/si_orchestrator/` and the legacy `Prometheous/` package.

## Language assignment (locked)

| Language | Role | Status in repo |
|----------|------|----------------|
| **Python** | Host orchestrator, registry, agents, learning coordinator, APIs | Phase 1 **live** |
| **Rust** | Memory fabric, Hopfield, CRDT, crypto, parallel kernels | **Stub** crate `rust_extensions/` → Phase 2 PyO3 |
| **Lisp (LYSP)** | Symbolic rules, CTMS, self-mod synthesis | **Python rules stand-in** `symbolic/rules.py` → Phase 2 bridge |
| **C++** | Only if hardware kernels force it | Not started (correct) |

**Primary host:** Python. **Wire format:** JSON (`schema_version: 1.0.0`).  
**Bindings later:** PyO3 (Rust), FFI/embed for Lisp.

## Dual-brain cognitive model

```text
                    ┌─────────────────────────────┐
   goal ──────────► │  SIOrchestrator (Python)    │
                    │  perceive → recall → act →  │
                    │  learn → remember           │
                    └──────────┬──────────────────┘
           ┌───────────────────┼───────────────────┐
           ▼                   ▼                   ▼
   Fast / intuitive      Slow / deliberative    Meta
   (vector/Hopfield)     (symbolic rules/Lisp)  (learning)
   memory/hopfield_*     symbolic/*             learning/*
```

Matches your **GFS Neuro-Symbolic Hopfield** + dual-brain node idea:
- **Fast path:** associative similarity (`HopfieldMemoryBackend` now; Rust later).
- **Slow path:** rule fire + (future) Lisp verification.
- **Working vs long-term:** working = cycle context; long-term = JSON/Hopfield store (Rust LTM later).

## Coverage vs your enhancement list

| Requirement | Phase 1 (now) | Phase 2+ |
|-------------|----------------|----------|
| Neuro-Symbolic Hopfield | `memory/hopfield_py.py` | Rust continuous/sparse Hopfield |
| Hierarchical / episodic + forgetting | tags + consolidate stub | HTM / sleep consolidation |
| Multi-modal index | text + tags + provenance | vector+graph+CRDT fusion |
| Hybrid query engine | `HybridRecall` (JSON∪Hopfield) | + Lisp pattern + graph |
| Provenance & confidence | `MemoryRecord.provenance`, `score` | full audit / RVI-CTMS |
| Dual-brain recall | hybrid + symbolic in one cycle | async verify channel |
| Continual learning | `ReplayLearningStrategy` | EWC, meta-learn (Rust opts) |
| Experience replay / sleep | buffer + `improve()` | offline consolidation worker |
| RL / self-supervised hooks | `observe()` contract | reward adapters |
| Lisp rule synthesis | rule strings in Python | LYSP embed + codegen |
| Observability / safety | traces on `CycleResult` | CTMS + alignment gates |
| JSON schemas | `config/schemas/*` | agent/task/state suite |

## Directory map

```text
/home/popi/Prometheous/
  master/Prometheous/     # existing agent swarm, brain, memory vault (legacy)
  work1/
    Prometheous/          # worktree of same package
    si_orchestrator/      # NEW SI spine (this design)
      core/               # orchestrator, registry, ABCs
      memory/             # JSON + Hopfield-Py + hybrid
      learning/           # replay + coordinator
      symbolic/           # rules (+ future lysp_bridge)
      agents/             # prometheus synthetic agent
      config/             # default.json + schemas
      rust_extensions/    # Cargo stub
      tests/
```

## Cycle (owned by Python, not by an LLM)

1. **Recall** hybrid (fast vector-ish + durable JSON) with provenance  
2. **Symbolic** query (deliberative)  
3. **Route agent** by skills  
4. **Act** (`PrometheusAgent` native plan/synthesize)  
5. **Store** episode  
6. **Learn** `observe` + `improve`  

External LLMs (existing `Prometheous/main.py` gateway) stay **phrasing tools**, not decision owners — same principle as your SGE notes.

## Integration with legacy Prometheous

Do **not** delete `core/orchestrator.py` / swarm agents yet. Bridge later:

```python
# conceptual
from si_orchestrator.bootstrap import build_orchestrator
si = build_orchestrator()
# register GhostGoat tools as Agent adapters
# optional: feed si.run() results into llm.respond() for user phrasing
```

## Next build priorities (recommended order)

1. **Memory fabric (you)** — dual store, hybrid recall, schemas ← *in progress / Phase 1 done*  
2. **Learning coordinator** — sleep cycles, EWC hook interface  
3. **Rust PyO3** — replace hopfield_py hot path  
4. **Lisp bridge** — LYSP eval for rule synthesis  
5. **Wire** SI into `Prometheous/main.py` REPL as default brain  
