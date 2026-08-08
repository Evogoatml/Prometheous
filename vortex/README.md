# Neureact Vortex

**SuperPrompt + GraphRAG + Recursive Memory** for Prometheous — built around [NeoVertex1/SuperPrompt](https://github.com/NeoVertex1/SuperPrompt).

CTMS here means **Causal Thought Management System** (thought-tree → traverse → flatten-tree), not clinical trials.

## Layout

```
vortex/
  superprompt/     # NeoVertex v1, ΩΣ v2, CTMS activation, Vortex fusion renderer
  memory/          # RecursiveMemoryDB (chunk → summary → meta + RECURS_TO)
  indexing/        # GraphExtractor + VortexGraphIndex (hybrid vector + hops)
  training/        # Synthetic SFT/DPO for SuperPrompt traces
  agent/           # CTMSVortexAgent OODA-style loop
core/graphrag/     # GraphRAGEngine adapter for NeuroReactCognitiveEngine
config/vortex_finetune.yaml
scripts/build_vortex_dataset.py
```

## Quick start

```bash
# Smoke-test agent (offline, no API keys)
python scripts/build_vortex_dataset.py --demo-agent

# Build fine-tune JSONL
python scripts/build_vortex_dataset.py
python scripts/build_vortex_dataset.py --scale 10   # larger mix

# Outputs → data/learning/finetune_vortex/
#   sft_train.jsonl  sft_val.jsonl  sft_test.jsonl  dpo_train.jsonl  manifest.json
```

## Training path

1. **SFT** on `sft_train.jsonl` (ChatML) with QLoRA (Unsloth / Axolotl) on Llama-3.1-8B+.
2. **DPO** on `dpo_train.jsonl` — prefers SuperPrompt/evidence traces over ungrounded PROCEED.
3. **Eval** hold-out: SuperPrompt tag presence, multi-hop fact match, recursion depth coherence.

## Runtime usage

```python
from vortex import CTMSVortexAgent, SuperPromptRenderer, RecursiveMemoryDB

agent = CTMSVortexAgent()
agent.ingest(open("docs/notes.md").read(), source="notes")
result = agent.run("How does SuperPrompt relate to GraphRAG?")
print(result["answer"])
print(result["trace"])
```

Optional LLM:

```python
def llm(system, user):
    # call Grok / Ollama / etc.
    ...

agent = CTMSVortexAgent(llm_fn=llm)
```

## SuperPrompt variants

| Variant | Use |
|---------|-----|
| `vortex` | GraphRAG + recursive memory tool contract (default) |
| `neovertex_v1` | Classic holographic answer_operator |
| `omega_v2` | Bounded SuperPrompt ΩΣ (v2 test1) |
| `ctms` | CTMS activation only |

```python
from vortex.superprompt import SuperPromptRenderer
print(SuperPromptRenderer("vortex").render(task="site selection reasoning"))
```

## Next upgrades

- Neo4j / FalkorDB backend for production Cypher recursion
- LLM-backed `GraphExtractor(llm_fn=...)` for high-quality NER/RE
- Unsloth train script pointed at `finetune_vortex/`
- Wire `CTMSVortexAgent` into `swarm/` / Telegram gateway
