# Synthetic Intelligent Orchestrator — Design Notes

Source reference (learning only, not forking): `d3fq0n1/maestro-orchestrator` at `~/Prometheous/../_refs/maestro-orchestrator/`

Goal: build a *better* orchestrator for Prometheous, informed by the patterns that
work in maestro and the patterns that are weak or missing in maestro. No code is
copied. Patterns are ported, not files.

---

## 1. What maestro does well (lift these)

### 1.1 Strict pipeline shape with named stages

`maestro/orchestrator.py:59` defines a fixed 6-stage pipeline:
0. Conversational — fan out to all agents in parallel
1. Deliberation — each agent reads peer responses, refines its reply (N rounds)
2. Dissent — pairwise semantic distance, outlier detection
3. NCG — headless baseline, drift/silent-collapse detection
4. Aggregation — synthesize quorum + confidence
5. R2 — grade, signal, index into ledger

Each stage has clear input/output, can be skipped or mocked, and emits
structured data. Every downstream stage reads from the previous stage's
contract, not from ad-hoc globals.

**Lift:** Prometheous's `core/orchestrator.py:82` dispatch() is one-shot
(intake → agent → result). We need a multi-stage pipeline shape that
dissent/R2/MAGI-style layers can plug into.

### 1.2 Deliberation as a first-class stage (not a prompt hack)

`maestro/deliberation.py:142` runs N rounds. Each round:
- Re-prompts each agent with its own previous reply + all peer replies
- Asks the agent to affirm, refine, or challenge
- Failed agents keep their previous-round response (graceful degradation)
- Skips if fewer than 2 clean agents

This is a real debate, not "ask the LLM again." The deliberation report
preserves every round for audit.

**Lift:** A `DeliberationStage` in our new orchestrator. Critically — and
this is where maestro is weak — each "agent" in Prometheous is not an LLM
but a `BaseAgent.execute(payload)` call. So our deliberation needs to work
on `payload → dict` outputs, not strings. That changes the implementation
but preserves the structure: round 0 = first execute, round N = re-execute
with peer context, refine or replace.

### 1.3 Dissent as a stage, not a vibe

`maestro/dissent.py` measures internal agreement and flags outliers
per-session. Critically, the dissent score feeds INTO NCG's silent-collapse
detector — high agreement + high drift = collapse. The two signals
complement each other.

**Lift:** A `DissentStage` that operates on agent outputs. For
Prometheous, since agents return structured dicts (not text), dissent
should be measured on:
- Result status (ok/failed/timeout/stub)
- Key agreement (intersection of output keys across agents)
- Confidence values
- Anomaly flags (any agent returned not_implemented, error, etc.)

### 1.4 R2 — explicit quality grading per session

`maestro/r2.py` scores every session on a fixed scale (strong,
acceptable, weak, suspicious) with a confidence score and flags. It
indexes every session into a persistent ledger. This is not a metric —
it's the system's memory of its own quality.

**Lift:** An `R2Stage` (or `QualityLedger` if we want our own name) that:
- Grades every orchestrated session
- Detects improvement signals
- Persists to SQLite/JSONL ledger keyed by session_id
- Is queryable: "what's the trend over the last 50 sessions?"

### 1.5 MAGI — read-only meta-analyzer

`maestro/magi.py:97` is the single most important pattern in maestro.
It reads the R2 ledger, never writes, and produces structured
`Recommendation` objects. Categories: agent, prompt, system, code,
positive. Severities: info, warning, critical.

Critical: **MAGI never auto-applies.** It observes and proposes. The
ethical constraint is encoded in the design, not in a config flag.

**Lift:** A `MetaAnalyzer` in Prometheous that reads our QualityLedger
and produces recommendations. This is currently missing or weak — we
have `paradox/paradox_aware_orchestrator.py` doing per-decision audits,
but no cross-session pattern detection.

### 1.6 Error-sentinel pattern with non-fatal pipeline

`maestro/orchestrator.py:20` defines a regex for error sentinels like
`[AgentName] HTTP 429` / `Timeout` / `Failed`. Every stage checks
`_is_agent_error(resp)` and excludes errored agents from analysis. The
whole pipeline is non-fatal: one agent's failure doesn't kill the run.

**Lift:** Standardize the error contract. Right now Prometheous agents
return `{"status": "failed", "error": "..."}` or `{"status": "ok",
"result": ...}` or raise. We need a single `is_error(result)` predicate
all stages share.

### 1.7 Hook system for extensibility

`maestro/orchestrator.py:127, 161, 237, 249, 253, 277, 282, 321` define
pre/post hooks for every stage (pre_orchestration, post_agent_response,
pre_aggregation, etc.). This is what makes the mod/plugin system viable.

**Lift:** A simple `StageHook` registry in our orchestrator. Pre/post
hooks at each stage boundary, callable list, no magic.

---

## 2. What maestro does poorly or wrong (don't copy these)

### 2.1 Hard-coded for multi-LLM, not multi-agent

Maestro's `agents` are LLM API clients. The whole pipeline assumes
text-in, text-out. Prometheous's agents are capability modules
(`BaseAgent.execute(payload) -> dict`). The translation is non-trivial —
if we just port maestro's loop, we break.

**Our version:** Stages operate on dict payloads and dict results.
String-based deliberation becomes payload-based refinement.

### 2.2 LLM-decides-everything anti-pattern

`run_orchestration_async()` asks multiple LLMs the same question and
takes a majority. This is expensive, slow, and (per maestro's own MAGI
analysis) prone to silent collapse from RLHF conformity.

**Our version:** Prometheous's LLM scope rule (the build-from-reference
skill calls this out explicitly): **default no LLM in decision engines.**
We use rule-based aggregation. LLM is only for phrasing, only if the
user opts in.

### 2.3 No learning from R2 ledger

Maestro detects "improvement signals" but never closes the loop. The
self-improvement engine (MAGI_VIR, `magi_vir.py`) is gated behind
`MAESTRO_AUTO_INJECT` and never turned on in production. So R2 detects
problems, MAGI writes recommendations, and... nothing happens.

**Our version:** Wire `learning/healing/` and `learning/optimizer.py`
into the recommendation path. Recommendations become real proposals
that go through the existing `learning/healing/applier.py` with human
review. Close the loop.

### 2.4 Async-only

Maestro is `async def run_orchestration_async()`. Prometheous's
`BaseAgent.execute()` is sync. Async/sync mismatch is the #1 source of
silent dispatch failures in this codebase (per the prometheous skill).

**Our version:** Sync-first. Optional async wrapper for streaming UIs.
The pipeline stages are sync functions; async only at the I/O boundary
(LLM calls, web search).

### 2.5 Monolithic orchestrator.py

699 lines, does everything. Hard to test, hard to extend.

**Our version:** Each stage is its own file. Pipeline is a list of
stages. Adding a stage is one line in the config.

### 2.6 WeightHost/WeightNode/MaestrOS thesis is a distraction

90% of the codebase (orchestrator.py, registry, storage_proof,
shard_manager, MaestrOS Rust workspace) implements a distributed
inference thesis that has nothing to do with our orchestration
problem. The Rust workspace is 9 empty crates. The Python side is
plumbing for shard storage and reputation scoring.

**Our version:** Ignore entirely. The thesis pattern that IS valuable
(capability manifest, weight locality score as a routing factor) is
already in Prometheous as `core/orchestrator/polymorphic_swarm.py`
and `kernel/service_registry.py`.

---

## 3. The new orchestrator — shape

Target: `core/orchestrator_v2/` (sibling to existing `core/orchestrator/`,
not a replacement). Old orchestrator stays for compatibility; new
orchestrator is opt-in per dispatch.

```
core/orchestrator_v2/
    pipeline.py          # Pipeline, Stage protocol, run()
    stages/
        intake.py        # Stage 0: build session, capture intent
        fanout.py        # Stage 1: dispatch to N agents in parallel
        deliberation.py  # Stage 2: N rounds of peer-aware refinement
        dissent.py       # Stage 3: per-agent agreement, outlier flags
        aggregate.py     # Stage 4: quorum/consensus
        quality.py       # Stage 5: R2-style grade + index to ledger
    ledger.py            # SQLite-backed quality ledger
    hooks.py             # pre/post stage hooks
    errors.py            # is_error(result) predicate
    meta.py              # MAGI-style cross-session analyzer
    config.py            # PipelineStageConfig, defaults
```

Plus wiring:
- `core/orchestrator.py` `dispatch()` gets a new branch:
  `if decision.action == "orchestrate_v2": OrchestratorV2.run(payload)`
- `learning/optimizer.py` consumes `meta.Recommendation` outputs
- `paradox/paradox_aware_orchestrator.py` becomes one of the
  dissent/quality signals, not the only auditor

---

## 4. Stage contracts (the actual work)

Each stage is a callable: `Stage.run(ctx: SessionContext) -> SessionContext`.
Same context object flows through, each stage mutates the fields it
owns. No globals, no shared mutable state outside the context.

```python
@dataclass
class SessionContext:
    session_id: str
    intent: str
    payload: dict
    agent_results: dict[str, dict]   # name -> {status, result, error, latency}
    deliberation_history: list[dict] # round 0, round 1, ...
    dissent: dict                    # {agreement, outliers, flags}
    quality: dict                    # {grade, confidence, flags}
    final: dict                      # the chosen/quorum result
```

### Stage 0 — intake
Builds SessionContext. Validates payload. Logs to ledger (session
opened).

### Stage 1 — fanout
Identifies N agents relevant to intent (use existing
`core/decision.py` + capability registry). Runs them in parallel
(thread pool, not async — sync base). For each: calls
`agent.execute(payload)`, captures status, result, error, latency.
Stops early if quorum threshold is hit (configurable).

### Stage 2 — deliberation
N rounds (default 1, max 3). Each round:
- Builds per-agent refinement payload with peer results
- Calls `agent.execute(refined_payload)` for each
- New result replaces old for downstream stages
- Failed agents keep previous-round result (per maestro)

### Stage 3 — dissent
Pure function over `agent_results`. Outputs:
- `agreement_score` (0-1, fraction of agents that returned ok)
- `outliers` (agents whose status/keys differ from majority)
- `silent_collapse_flag` (high agreement + high result similarity
  with no independent signal — modified for our case: if all
  successful agents returned the same `result` dict, flag it)

### Stage 4 — aggregate
Combines results. Rule-based: highest-confidence ok result wins;
or quorum if N agents agree; or all-of if intent requires. Never
LLM-decided. Outputs `final` dict.

### Stage 5 — quality
Grades the session: A/B/C/D based on (agreement, dissent, latency,
failures). Indexes to ledger. Detects improvement signals:
- Same agent failed 3x in a row
- Confidence trending down for this intent
- New outlier pattern

### Meta stage (separate, not in pipeline) — meta.py
Reads ledger. Produces `Recommendation` objects. Categories:
agent (high failure rate), intent (chronic low confidence), system
(no agents available for X), positive (this agent's quality is
trending up). **Never auto-applies.** Writes to
`data/quality_recommendations.jsonl`. The existing
`learning/healing/` pipeline reads this file.

---

## 5. What this does NOT do

- Does not replace the existing `core/orchestrator.py`. It runs
  alongside it. v2 is opt-in via `action: "orchestrate_v2"`.
- Does not introduce async. Sync pipeline, sync stages, sync agents.
- Does not call the LLM for any decision. LLM is opt-in for
  phrasing only (existing `core/gateway.py`).
- Does not auto-apply recommendations. Human review required.
- Does not copy maestro's WeightHost/storage_proof/MaestrOS
  subsystems. Those are not relevant to Prometheous.

---

## 6. Build order

1. `errors.py` — single `is_error(result)` predicate. One file.
2. `ledger.py` — SQLite schema, write/read. Two functions.
3. `pipeline.py` — Stage protocol, SessionContext, run().
4. `stages/intake.py` + `stages/fanout.py` — minimal vertical slice.
5. Wire v2 into `core/orchestrator.py` as new action.
6. `stages/aggregate.py` — rule-based aggregation.
7. `stages/quality.py` — grading + ledger indexing.
8. `stages/dissent.py` — agreement/outlier analysis.
9. `stages/deliberation.py` — N-round peer refinement.
10. `meta.py` — cross-session recommendation engine.
11. Wire `learning/healing/` to consume recommendations.
12. End-to-end test: dispatch a real task via v2, verify ledger,
    verify meta produces a recommendation, verify healing proposes
    a fix (not auto-applies).

Each step ends with a runnable test. No step that leaves the system
in a broken state.

---

## 7. Verification

After step 12:
- `.venv/bin/python main.py --no-repl` still boots (v1 unaffected)
- A test that calls `orchestrator_v2.run({...})` directly produces
  a SessionContext with all 6 stages populated
- The ledger at `data/quality_ledger.db` has the test session
- `meta.analyze()` over the test session produces at least one
  Recommendation
- `learning/healing/` reads the recommendation file and produces
  a proposal (not auto-applied)
- `paradox/paradox_aware_orchestrator.py` still runs on v1 dispatches

The deliverable is a working v2 orchestrator that runs alongside v1,
not a replacement. v1 stays as the stable path; v2 is the experimental
upgrade that proves the patterns.
