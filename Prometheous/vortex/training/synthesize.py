"""
Synthetic + structured training data for SuperPrompt + GraphRAG + recursive memory.

Produces ChatML SFT rows and DPO preference pairs that teach models to:
  - emit SuperPrompt / CTMS traces
  - use graph hops + recursive memory depth
  - prefer evidence-grounded answers over free hallucination
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from vortex.superprompt.renderer import SuperPromptRenderer
from vortex.superprompt.templates import REASONING_TRACE_TEMPLATE
from vortex.indexing.extract import GraphExtractor
from vortex.memory.recursive_memory import RecursiveMemoryDB, MemoryLevel


@dataclass
class VortexExample:
    category: str  # graph_extract | recursive_memory | superprompt_reason | multihop | ctms_branch
    query: str
    context: str
    assistant: str
    metadata: Dict[str, Any]

    def to_dict(self) -> dict:
        return asdict(self)


# Seed corpora for offline synthesis (domain-agnostic agent/knowledge tasks)
CORPUS_DOCS = [
    """GraphRAG builds a knowledge graph from documents using entity and relation extraction.
Community detection produces hierarchical summaries. Local search answers entity-focused questions;
global search uses community reports for corpus-level themes. SuperPrompt steers extraction with
XML answer_operator tags and recursion_engine for multi-hop reasoning.""",
    """Recursive memory stores episodic interactions as chunks, compresses them into summaries,
then meta-summaries. Agents traverse RECURS_TO edges to drill from global insight to raw detail.
This mirrors RAPTOR trees and MemGPT hierarchical context management without unbounded loops.""",
    """CTMS is a Causal Thought Management System from NeoVertex SuperPrompt: thought-tree → traverse → flatten-tree.
Operators include ♢ next-thought, ⋔ split-branch, ↑ transcend, ⍟ metamorphosis, § gödelize.
It is not a clinical trial product; it is a reasoning framework for agentic self-reference.""",
    """Neureact Vortex fuses SuperPrompt, GraphRAG, and recursive memory inside Prometheous.
NeuroReact runs OODA loops (observe-orient-decide-act) while writing thoughts and rewards into the graph.
Fine-tuning targets native SuperPrompt format, multi-hop accuracy, and low hallucination on retrieved facts.""",
    """QLoRA fine-tuning on 5k–20k high-quality traces adapts 8B–70B models to tool-calling agents.
SFT teaches format; DPO prefers revised thoughts over premature PROCEED. Evaluation: entity F1,
multi-hop accuracy, recursion coherence, and human review of long-chain answers.""",
    """Hybrid retrieval combines vector similarity with graph hops. Seed nodes expand via RELATED,
CAUSES, and RECURS_TO edges. Compressed memory context is injected into SuperPrompt
memory_state and graph_context slots before the final answer_operator.""",
]

MULTI_HOP_QA = [
    {
        "q": "How does SuperPrompt interact with GraphRAG indexing?",
        "facts": [
            "SuperPrompt steers extraction with XML answer_operator tags",
            "GraphRAG builds a knowledge graph from documents",
        ],
        "answer": (
            "SuperPrompt provides structured extraction guidance (answer_operator, recursion_engine); "
            "GraphRAG materializes those entities/relations into a searchable knowledge graph for multi-hop answers."
        ),
        "hops": 2,
    },
    {
        "q": "What is CTMS in NeoVertex SuperPrompt?",
        "facts": [
            "CTMS is a Causal Thought Management System",
            "thought-tree → traverse → flatten-tree",
            "not a clinical trial product",
        ],
        "answer": (
            "CTMS is SuperPrompt's Causal Thought Management System: expand a thought-tree, traverse branches "
            "with causal operators, then flatten into an interpretable chain. It is a reasoning framework, not clinical software."
        ),
        "hops": 2,
    },
    {
        "q": "Why bound recursive memory depth?",
        "facts": [
            "Agents traverse RECURS_TO edges",
            "without unbounded loops",
            "max_depth default 4",
        ],
        "answer": (
            "Recursive drill-down can explode context; Vortex bounds depth (default 4) like SuperPrompt v2's "
            "bounded_reasoning_protocol, truncating ∞ branches and compressing the path into memory_state."
        ),
        "hops": 2,
    },
    {
        "q": "What training stack fits Neureact Vortex agents?",
        "facts": [
            "QLoRA fine-tuning",
            "SFT teaches format",
            "DPO prefers revised thoughts",
        ],
        "answer": (
            "Use QLoRA SFT on SuperPrompt-formatted GraphRAG/memory traces, then DPO so the model prefers "
            "revised evidence-grounded answers over premature ungrounded PROCEED actions."
        ),
        "hops": 3,
    },
]


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def _build_ctms_trace(steps: List[str]) -> str:
    lines = []
    for i, s in enumerate(steps):
        op = "♢" if i < len(steps) - 1 else "⊨"
        lines.append(f"<{op}:step:{i}>{s}</>")
    return "\n".join(lines)


def generate_graph_extract_examples(rng: random.Random) -> List[VortexExample]:
    extractor = GraphExtractor()
    examples: List[VortexExample] = []
    for doc in CORPUS_DOCS:
        result = extractor.extract(doc)
        assistant = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        examples.append(
            VortexExample(
                category="graph_extract",
                query="Extract entities, relations, and recursive links for GraphRAG indexing.",
                context=doc,
                assistant=assistant,
                metadata={
                    "source": "vortex_synth",
                    "n_entities": len(result.entities),
                    "n_relations": len(result.relations),
                    "id": _stable_id("ge", doc[:80]),
                },
            )
        )
    return examples


def generate_recursive_memory_examples(rng: random.Random) -> List[VortexExample]:
    examples: List[VortexExample] = []
    mem = RecursiveMemoryDB(max_depth=4)
    for doc in CORPUS_DOCS:
        summary = doc[:160] + "…"
        meta = " ".join(doc.split()[:12]) + " [meta]"
        mem.store_episode(doc, summary=summary, meta_summary=meta)

    queries = [
        "recursive memory hierarchy",
        "GraphRAG community search",
        "CTMS thought-tree operators",
        "fine-tuning SuperPrompt agents",
    ]
    for q in queries:
        result = mem.recursive_search(q, top_k=3, max_depth=3)
        assistant = (
            f"<recursion_engine>\n"
            f"explore({q}) → seeds={result['seeds']} max_depth={result['max_depth']}\n"
            f"compressed: {result['compressed_context'][:400]}\n"
            f"</recursion_engine>\n"
            f"<final>\n"
            f"  <direct_answer>Retrieved hierarchical memory for '{q}' with "
            f"{len(result['paths'])} seed paths.</direct_answer>\n"
            f"  <memory_depth used=\"{result['max_depth']}\">{result['operator']}</memory_depth>\n"
            f"  <confidence>medium</confidence>\n"
            f"</final>\nY"
        )
        examples.append(
            VortexExample(
                category="recursive_memory",
                query=q,
                context=result["compressed_context"][:600],
                assistant=assistant,
                metadata={
                    "source": "vortex_synth",
                    "paths": len(result["paths"]),
                    "id": _stable_id("rm", q),
                },
            )
        )
    return examples


def generate_superprompt_reason_examples(rng: random.Random) -> List[VortexExample]:
    examples: List[VortexExample] = []
    for item in MULTI_HOP_QA:
        steps = item["facts"] + [item["answer"]]
        ctms = _build_ctms_trace(steps)
        assistant = REASONING_TRACE_TEMPLATE.format(
            meta_type="GraphRAG Multi-Hop",
            meta_purpose="Evidence-grounded agent reasoning",
            objective=item["q"][:80],
            query_compressed=item["q"][:100],
            insight=item["facts"][0][:120],
            root_concept=item["facts"][0].split()[0],
            depth=item["hops"],
            recursion_result=" → ".join(item["facts"]),
            ctms_trace=ctms,
            answer=item["answer"],
            hops=item["hops"],
            graph_summary="; ".join(item["facts"]),
            mem_depth=2,
            memory_summary="hierarchical summaries consulted",
            confidence="high",
        )
        examples.append(
            VortexExample(
                category="superprompt_reason",
                query=item["q"],
                context="\n".join(f"- {f}" for f in item["facts"]),
                assistant=assistant,
                metadata={
                    "source": "vortex_synth",
                    "hops": item["hops"],
                    "id": _stable_id("sp", item["q"]),
                },
            )
        )
    return examples


def generate_multihop_examples(rng: random.Random) -> List[VortexExample]:
    """Graph-index a corpus and emit retrieval-conditioned answers."""
    from vortex.indexing.index_graph import VortexGraphIndex

    index = VortexGraphIndex()
    for i, doc in enumerate(CORPUS_DOCS):
        index.add_document(doc, source=f"corpus_{i}")

    examples: List[VortexExample] = []
    for item in MULTI_HOP_QA:
        hits = index.query(item["q"], top_k=4, hops=item["hops"])
        graph_lines = []
        for nid, score, data in hits[:6]:
            graph_lines.append(f"- ({score:.2f}) {data.get('content', '')[:160]}")
        graph_ctx = "\n".join(graph_lines) or "(no hits)"
        assistant = REASONING_TRACE_TEMPLATE.format(
            meta_type="Hybrid GraphRAG Query",
            meta_purpose="Multi-hop relational reasoning",
            objective=item["q"][:80],
            query_compressed=item["q"][:100],
            insight=(hits[0][2].get("content", "")[:100] if hits else "no seed"),
            root_concept="GraphRAG",
            depth=item["hops"],
            recursion_result=f"{len(hits)} expanded nodes",
            ctms_trace=_build_ctms_trace(
                [f"seed:{hits[0][0]}" if hits else "seed:none"]
                + item["facts"][:2]
                + [item["answer"]]
            ),
            answer=item["answer"],
            hops=item["hops"],
            graph_summary=graph_ctx.replace("\n", " | ")[:300],
            mem_depth=2,
            memory_summary=index.memory.context_block(item["q"])[:200],
            confidence="high" if hits else "low",
        )
        examples.append(
            VortexExample(
                category="multihop",
                query=item["q"],
                context=graph_ctx,
                assistant=assistant,
                metadata={
                    "source": "vortex_synth",
                    "hits": len(hits),
                    "id": _stable_id("mh", item["q"]),
                },
            )
        )
    return examples


def generate_ctms_branch_examples(rng: random.Random) -> List[VortexExample]:
    scenarios = [
        {
            "q": "Is unbounded self-reference safe in agent loops?",
            "branches": [
                "♢ Bound recursion with max_depth",
                "⋔ Branch A: allow ∞ → context explosion",
                "⋔ Branch B: truncate + compress → stable",
                "⊨ Prefer Branch B with SuperPrompt v2 bounds",
            ],
            "answer": (
                "Unbounded self-reference is unsafe for production agents. Use CTMS with max_depth, "
                "truncate ∞, and compress via recursive memory summaries."
            ),
        },
        {
            "q": "When should the agent call memory_recursive_search?",
            "branches": [
                "♢ Detect historical / multi-session context need",
                "⋔ Shallow FAQ → vector only",
                "⋔ Long trial of decisions → recursive drill-down",
                "⊨ Use recursive search when depth or history matters",
            ],
            "answer": (
                "Call memory_recursive_search when the query needs historical evolution, multi-session "
                "state, or hierarchical compression — not for simple single-hop lookups."
            ),
        },
    ]
    examples: List[VortexExample] = []
    for s in scenarios:
        ctms = "\n".join(f"<{line[:1]}:trace:{i}>{line}</>" for i, line in enumerate(s["branches"]))
        assistant = (
            f"Action: branching CTMS exploration.\n"
            f"<answer_operator>\n{ctms}\n</answer_operator>\n"
            f"<final>\n  <direct_answer>{s['answer']}</direct_answer>\n"
            f"  <confidence>high</confidence>\n</final>\nY"
        )
        examples.append(
            VortexExample(
                category="ctms_branch",
                query=s["q"],
                context="CTMS operator algebra",
                assistant=assistant,
                metadata={"source": "vortex_synth", "id": _stable_id("ctms", s["q"])},
            )
        )
    return examples


def generate_vortex_examples(seed: int = 42) -> List[VortexExample]:
    rng = random.Random(seed)
    out: List[VortexExample] = []
    out.extend(generate_graph_extract_examples(rng))
    out.extend(generate_recursive_memory_examples(rng))
    out.extend(generate_superprompt_reason_examples(rng))
    out.extend(generate_multihop_examples(rng))
    out.extend(generate_ctms_branch_examples(rng))
    rng.shuffle(out)
    return out


def vortex_to_chat(
    example: VortexExample,
    system_prompt: Optional[str] = None,
    variant: str = "vortex",
) -> dict:
    """Map VortexExample → ChatML record dict (compatible with pipeline ChatRecord)."""
    if system_prompt is None:
        system_prompt = SuperPromptRenderer(variant=variant).with_context(
            task=example.category,
            memory_summary=example.context[:500] if example.category == "recursive_memory" else "",
            graph_hits=[(example.context, 1.0)] if example.context else None,
            objective=example.query[:120],
        )
    user = example.query
    if example.context and example.category in ("graph_extract", "multihop"):
        user = f"{example.query}\n\n<context>\n{example.context}\n</context>"

    return {
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user},
            {"role": "assistant", "content": example.assistant},
        ],
        "metadata": {
            **example.metadata,
            "category": example.category,
            "source": example.metadata.get("source", "vortex_synth"),
        },
    }


def vortex_to_dpo(example: VortexExample, system_prompt: Optional[str] = None) -> Optional[dict]:
    """Preference: full SuperPrompt trace (chosen) vs shallow ungrounded answer (rejected)."""
    if example.category not in ("superprompt_reason", "multihop", "ctms_branch", "recursive_memory"):
        return None
    if system_prompt is None:
        system_prompt = SuperPromptRenderer("vortex").render(task=example.query)

    rejected = (
        f"<thinking>I can answer without tools.</thinking>\n"
        f"<choice>PROCEED</choice>\n"
        f"<action>guess</action>\n"
        f"Probably something about AI agents. Confidence: high."
    )
    return {
        "prompt": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": example.query},
        ],
        "chosen": example.assistant,
        "rejected": rejected,
        "metadata": {
            "source": "vortex_dpo",
            "category": example.category,
            "id": _stable_id("vdpo", example.query),
        },
    }


def generate_stats(examples: List[VortexExample]) -> dict:
    by_cat: Dict[str, int] = {}
    for e in examples:
        by_cat[e.category] = by_cat.get(e.category, 0) + 1
    return {"total": len(examples), "by_category": by_cat}
