"""
Graph extraction for GraphRAG indexing.

Uses regex/heuristic offline extractors by default; optionally an LLM callable
with SuperPrompt GRAPH_EXTRACTION_PROMPT for higher quality labels.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional

from vortex.superprompt.templates import CTMS_ACTIVATION, GRAPH_EXTRACTION_PROMPT


@dataclass
class Entity:
    id: str
    name: str
    type: str = "Other"
    span: str = ""


@dataclass
class Relation:
    source: str
    target: str
    type: str = "RELATED"
    evidence: str = ""


@dataclass
class ExtractionResult:
    entities: List[Entity] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)
    memory_nodes: List[dict] = field(default_factory=list)
    recursive_links: List[dict] = field(default_factory=list)
    source_text: str = ""

    def to_dict(self) -> dict:
        return {
            "entities": [asdict(e) for e in self.entities],
            "relations": [asdict(r) for r in self.relations],
            "memory_nodes": self.memory_nodes,
            "recursive_links": self.recursive_links,
            "source_text": self.source_text[:500],
        }


# Capitalized multi-word phrases / known technical tokens
_ENTITY_RE = re.compile(
    r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3})\b"
    r"|\b(GraphRAG|SuperPrompt|CTMS|Neureact|Vortex|LangGraph|Neo4j|NetworkX|"
    r"QLoRA|RAG|MemGPT|RAPTOR|recursion_engine|answer_operator)\b"
)

_REL_PATTERNS = [
    (re.compile(r"(.+?)\s+(?:causes|leads to|results in)\s+(.+)", re.I), "CAUSES"),
    (re.compile(r"(.+?)\s+(?:uses|via|through)\s+(.+)", re.I), "USES"),
    (re.compile(r"(.+?)\s+(?:part of|within|inside)\s+(.+)", re.I), "PART_OF"),
    (re.compile(r"(.+?)\s+(?:evolves into|becomes|transforms into)\s+(.+)", re.I), "EVOLVES_INTO"),
    (re.compile(r"(.+?)\s+(?:contradicts|conflicts with)\s+(.+)", re.I), "CONTRADICTS"),
    (re.compile(r"(.+?)\s+(?:related to|links to|connected to)\s+(.+)", re.I), "RELATED"),
]


class GraphExtractor:
    """Entity + relation extraction for Vortex GraphRAG."""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        """
        llm_fn: optional callable(prompt) -> text; if set, used for LLM extraction
        with SuperPrompt schema. Falls back to heuristics on parse failure.
        """
        self.llm_fn = llm_fn

    def extract(self, text: str) -> ExtractionResult:
        text = (text or "").strip()
        if not text:
            return ExtractionResult(source_text="")

        if self.llm_fn is not None:
            try:
                return self._extract_llm(text)
            except Exception:
                pass
        return self._extract_heuristic(text)

    def _extract_llm(self, text: str) -> ExtractionResult:
        prompt = GRAPH_EXTRACTION_PROMPT.format(
            ctms_header=CTMS_ACTIVATION,
            text=text[:6000],
        )
        raw = self.llm_fn(prompt)
        # strip fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        entities = [
            Entity(
                id=e.get("id", f"e{i}"),
                name=e.get("name", ""),
                type=e.get("type", "Other"),
                span=e.get("span", e.get("name", "")),
            )
            for i, e in enumerate(data.get("entities") or [])
            if e.get("name")
        ]
        name_to_id = {e.name: e.id for e in entities}
        relations = []
        for r in data.get("relations") or []:
            src = r.get("source")
            tgt = r.get("target")
            # allow names or ids
            if src in name_to_id:
                src = name_to_id[src]
            if tgt in name_to_id:
                tgt = name_to_id[tgt]
            relations.append(
                Relation(
                    source=str(src),
                    target=str(tgt),
                    type=r.get("type", "RELATED"),
                    evidence=r.get("evidence", ""),
                )
            )
        return ExtractionResult(
            entities=entities,
            relations=relations,
            memory_nodes=list(data.get("memory_nodes") or []),
            recursive_links=list(data.get("recursive_links") or []),
            source_text=text,
        )

    def _extract_heuristic(self, text: str) -> ExtractionResult:
        found: Dict[str, Entity] = {}
        for m in _ENTITY_RE.finditer(text):
            name = (m.group(1) or m.group(2) or "").strip()
            if len(name) < 2 or name.lower() in {"the", "this", "that", "and", "for"}:
                continue
            # skip sentence starts that are common English
            if name in {"Action", "Objective", "Task", "Type", "Purpose"}:
                continue
            eid = f"e_{len(found)+1}"
            if name not in found:
                etype = "Concept" if name[0].isupper() else "Other"
                if name in (
                    "GraphRAG",
                    "SuperPrompt",
                    "CTMS",
                    "Neureact",
                    "Vortex",
                    "LangGraph",
                    "Neo4j",
                    "NetworkX",
                    "QLoRA",
                    "RAG",
                    "MemGPT",
                    "RAPTOR",
                ):
                    etype = "Tool"
                found[name] = Entity(id=eid, name=name, type=etype, span=name)

        entities = list(found.values())
        id_by_name = {e.name: e.id for e in entities}
        relations: List[Relation] = []

        for sentence in re.split(r"[.\n;]+", text):
            s = sentence.strip()
            if len(s) < 8:
                continue
            for pat, rtype in _REL_PATTERNS:
                m = pat.search(s)
                if not m:
                    continue
                left, right = m.group(1).strip(), m.group(2).strip()
                # match entities mentioned in sides
                src = self._match_entity(left, id_by_name)
                dst = self._match_entity(right, id_by_name)
                if src and dst and src != dst:
                    relations.append(
                        Relation(source=src, target=dst, type=rtype, evidence=s[:200])
                    )

        # If few relations, co-occur consecutive entities as RELATED
        if len(relations) < 2 and len(entities) >= 2:
            for a, b in zip(entities, entities[1:]):
                relations.append(
                    Relation(source=a.id, target=b.id, type="RELATED", evidence="co-occurrence")
                )

        # Memory nodes: chunk + crude summary
        summary = text[:200].replace("\n", " ") + ("…" if len(text) > 200 else "")
        memory_nodes = [
            {"level": "chunk", "content": text[:500], "parent_of": []},
            {"level": "summary", "content": summary, "parent_of": ["chunk"]},
        ]
        recursive_links = []
        if len(entities) >= 2:
            recursive_links.append(
                {
                    "from": entities[0].id,
                    "to": entities[1].id,
                    "depth_hint": 1,
                    "operator": "explore",
                }
            )

        return ExtractionResult(
            entities=entities,
            relations=relations,
            memory_nodes=memory_nodes,
            recursive_links=recursive_links,
            source_text=text,
        )

    @staticmethod
    def _match_entity(fragment: str, id_by_name: Dict[str, str]) -> Optional[str]:
        for name, eid in id_by_name.items():
            if name in fragment or fragment in name:
                return eid
        return None
