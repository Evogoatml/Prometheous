"""
CTMS Vortex agent — SuperPrompt answer_operator loop over GraphRAG + recursive memory.

Offline-capable: uses local retrieval always; optional LLM for final synthesis.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from vortex.indexing.index_graph import VortexGraphIndex
from vortex.memory.recursive_memory import RecursiveMemoryDB
from vortex.superprompt.renderer import SuperPromptRenderer


@dataclass
class AgentStep:
    operator: str
    phase: str
    detail: str
    data: Dict[str, Any] = field(default_factory=dict)


class CTMSVortexAgent:
    """
    Minimal Neureact Vortex agent:
      thought-tree → traverse (graph + memory) → flatten-tree → answer
    """

    def __init__(
        self,
        index: Optional[VortexGraphIndex] = None,
        memory: Optional[RecursiveMemoryDB] = None,
        renderer: Optional[SuperPromptRenderer] = None,
        llm_fn: Optional[Callable[[str, str], str]] = None,
        max_depth: int = 4,
    ):
        self.index = index or VortexGraphIndex()
        self.memory = memory or self.index.memory
        self.renderer = renderer or SuperPromptRenderer("vortex")
        self.llm_fn = llm_fn  # (system, user) -> assistant text
        self.max_depth = max_depth
        self.trace: List[AgentStep] = []

    def ingest(self, text: str, source: str = "session") -> dict:
        return self.index.add_document(text, source=source)

    def run(self, query: str, *, store_episode: bool = True) -> Dict[str, Any]:
        self.trace = []
        t0 = time.time()

        # ♢ observe
        self._step("♢", "observe", f"query={query[:120]}")
        graph_hits = self.index.query(query, top_k=5, hops=2)
        mem_result = self.memory.recursive_search(query, top_k=4, max_depth=self.max_depth)

        # ⋔ branch retrieval modes
        self._step(
            "⋔",
            "split-branch",
            "graph hybrid + recursive memory",
            {
                "graph_hits": len(graph_hits),
                "memory_paths": len(mem_result.get("paths", [])),
            },
        )

        graph_context_lines = []
        for nid, score, data in graph_hits[:6]:
            graph_context_lines.append(
                f"[{score:.2f}] ({data.get('node_type')}) {data.get('content', '')[:200]}"
            )
        graph_context = "\n".join(graph_context_lines) or "(none)"
        memory_state = mem_result.get("compressed_context", "")[:800]

        # ⍟ metamorphosis → system prompt with live state
        system = self.renderer.render(
            task=query,
            objective=query[:160],
            memory_state=memory_state or "(empty)",
            graph_context=graph_context,
        )
        self._step("⍟", "metamorphosis", "render SuperPrompt with live graph/memory")

        # ↑ synthesize
        if self.llm_fn:
            try:
                answer = self.llm_fn(system, query)
                self._step("↑", "transcend", "LLM synthesis")
            except Exception as e:
                answer = self._local_synthesize(query, graph_hits, mem_result)
                self._step("↺", "fallback", f"LLM failed: {e}")
        else:
            answer = self._local_synthesize(query, graph_hits, mem_result)
            self._step("⊨", "truth", "local evidence synthesis")

        if store_episode:
            summary = answer[:200]
            self.memory.store_episode(
                f"Q: {query}\nA: {answer[:500]}",
                summary=summary,
                meta_summary=f"resolved:{query[:80]}",
            )

        latency = (time.time() - t0) * 1000
        return {
            "query": query,
            "answer": answer,
            "system_prompt_chars": len(system),
            "graph_hits": len(graph_hits),
            "memory": {
                "seeds": mem_result.get("seeds"),
                "max_depth": mem_result.get("max_depth"),
                "compressed": memory_state[:300],
            },
            "trace": [
                {"operator": s.operator, "phase": s.phase, "detail": s.detail, **s.data}
                for s in self.trace
            ],
            "latency_ms": latency,
            "answer_operator_used": "Y",
        }

    def _local_synthesize(
        self,
        query: str,
        graph_hits: list,
        mem_result: dict,
    ) -> str:
        facts = []
        for _, score, data in graph_hits[:4]:
            facts.append(f"- ({score:.2f}) {data.get('content', '')[:180]}")
        mem_bits = mem_result.get("compressed_context", "")[:300]
        fact_block = "\n".join(facts) if facts else "- (no graph evidence)"
        ctms = "\n".join(
            f"<♢:step:{i}>{s.phase}: {s.detail}</>"
            for i, s in enumerate(self.trace)
        )
        return (
            f"Action: formalizing, graph-traversing, and verifying.\n"
            f"<prompt_metadata>\n"
            f"Type: Vortex Local Synthesis\n"
            f"Purpose: Evidence-grounded answer without external LLM\n"
            f"Objective: {query[:100]}\n"
            f"</prompt_metadata>\n"
            f"<think>\n?({query[:80]}) → !(retrieve+compress+answer)\n</think>\n"
            f"<recursion_engine>\n{mem_result.get('operator')} depth={mem_result.get('max_depth')}\n"
            f"</recursion_engine>\n"
            f"<answer_operator>\n{ctms}\n</answer_operator>\n"
            f"<final>\n"
            f"  <direct_answer>\n"
            f"Based on GraphRAG + recursive memory:\n{fact_block}\n"
            f"Memory: {mem_bits}\n"
            f"  </direct_answer>\n"
            f"  <graph_hops used=\"{min(2, len(graph_hits))}\">{len(graph_hits)} nodes</graph_hops>\n"
            f"  <memory_depth used=\"{mem_result.get('max_depth', 0)}\">recursive_search</memory_depth>\n"
            f"  <confidence>{'medium' if graph_hits else 'low'}</confidence>\n"
            f"</final>\n"
            f"Y"
        )

    def _step(self, operator: str, phase: str, detail: str, data: Optional[dict] = None):
        self.trace.append(AgentStep(operator=operator, phase=phase, detail=detail, data=data or {}))
