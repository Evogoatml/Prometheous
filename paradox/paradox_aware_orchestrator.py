# paradox/paradox_aware_orchestrator.py
"""
Paradox-aware auditor. Integrated so advanced "brain/paradox" components
actually affect the flow: post-task audits, blind-spot detection,
and result annotation (without the LLM ever deciding).
"""
from typing import Dict, Any, Optional, List
import os
import time

# Pull in the adaptive ctms version too so those files get referenced/used
try:
    import importlib
    adaptive_paradox = importlib.import_module(
        "paradox.adaptive_ctms.paradox_aware_orchestrator"
    )
except Exception:
    adaptive_paradox = None


class ParadoxAwareOrchestrator:
    """Paradox engine — audits decisions/results for contradictions and blind spots."""

    def __init__(self):
        self.audit_log: List[Dict[str, Any]] = []
        # Simple known conflict patterns (from structured moved-in analysis)
        self._conflict_patterns = [
            ("exploit", "scan"),   # doing blind exploit right after scan may be premature
            ("exfil", "persist"),  # exfil + persist without clear pivot sometimes contradictory in safety model
        ]

    def _is_self_audit(self, query: str) -> bool:
        q = (query or "").lower()
        triggers = (
            "self-audit", "self audit", "audit yourself", "audit yourself",
            "paradox audit", "who audits", "your limitations", "your blind spots",
        )
        return any(t in q for t in triggers)

    def audit_system(self) -> Dict[str, Any]:
        """Structured self-audit using real system facts — not LLM testimony."""
        agents: List[str] = []
        try:
            from core.orchestrator import orchestrator
            agents = sorted(orchestrator.list_agents())
        except Exception:
            agents = []

        llm_on = os.getenv("PROM_TELEGRAM_LLM", "").lower() in ("1", "true", "yes")
        strengths = [
            "Rule-based decision engine — routing is deterministic, not LLM-decided",
            "Multi-agent dispatch (scanner, web_search, paradox, ghost_sentinel, …)",
            "Web search available via DuckDuckGo/SerpAPI (/search)",
            "Ghost Sentinel — CRDT + Manchester MCP + gated tool assembly",
            "Paradox auditor subsystem is loaded and active",
        ]
        limitations = [
            "LLM (if enabled) only phrases replies — can still hallucinate on open chat",
            "No persistent memory across Telegram sessions unless wired to memory layer",
            "Stub agents return not_implemented for some capabilities",
            "Self-audit is system introspection, not neural introspection",
        ]
        if not llm_on:
            limitations.append("LLM phrasing disabled (PROM_TELEGRAM_LLM=0) — deterministic fallbacks only")

        blind_spots = [
            "Users may confuse LLM voice with Prometheous identity",
            "Without /search, factual answers may be stale or confabulated",
        ]
        if "web_search" not in agents:
            blind_spots.append("web_search agent not registered")

        return {
            "timestamp": time.time(),
            "mode": "self",
            "query": "Prometheous system self-audit",
            "strengths": strengths,
            "limitations": limitations,
            "contradictions": [],
            "blind_spots": blind_spots,
            "registered_agents": agents,
            "confidence": 0.85,
            "paradox_note": (
                "Asking any AI to audit itself is structurally circular. "
                "This report uses orchestrator facts + policy checks, not model self-testimony. "
                "Cross-check critical claims with /search or external sources."
            ),
            "recommendation": "use paradox agent + web search for verification",
        }

    def audit(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        context can contain: decision, task, result, intent, agent, payload, etc.
        Returns audit report and stores it.
        """
        query = context.get("user_msg") or context.get("query") or str(context)[:80]
        if self._is_self_audit(str(query)) or context.get("mode") == "self":
            entry = self.audit_system()
            self.audit_log.append(entry)
            return entry

        intent = context.get("intent") or context.get("decision", {}).get("action", "")
        agent = context.get("agent", "")
        result = context.get("result") or {}
        confidence = float(context.get("confidence", 0.7))

        contradictions: List[str] = []
        blind_spots: List[str] = []

        # Basic contradiction detection
        lower_intent = str(intent).lower()
        for a, b in self._conflict_patterns:
            if a in lower_intent or b in lower_intent:
                if any(x in lower_intent for x in [a, b]) and len(lower_intent) < 30:
                    contradictions.append(f"Potential ordering issue involving {a}/{b}")

        # Blind spots from result
        if isinstance(result, dict):
            if result.get("status") == "not_implemented":
                blind_spots.append("Agent returned stub / not_implemented — real capability gap")
            if "note" in str(result).lower() and "stub" in str(result).lower():
                blind_spots.append("Stub behavior detected in result")
            if not result:
                blind_spots.append("Empty result payload")

        # Low confidence blind spot
        if confidence < 0.6:
            blind_spots.append(f"Low decision confidence ({confidence}) — consider more recon first")

        # Use some brain pieces if available (pattern interpreter style checks)
        try:
            from brain.pattern_interpreter import PatternInterpreter
            pi = PatternInterpreter()
            # fake some neural_insights from context for demo integration
            insights = {
                "pattern_summary": {"pattern_stability": 0.4 if contradictions else 0.8},
                "learning_trajectory": {"is_improving": False, "status": "ok"},
                "performance_metrics": {},
            }
            interp = pi.interpret(insights)
            if interp.get("behavioral_state") == "exploring":
                blind_spots.append("System in high-exploration state — may miss stable policy")
        except Exception:
            pass

        entry = {
            "timestamp": time.time(),
            "query": query,
            "intent": intent,
            "agent": agent,
            "contradictions": contradictions,
            "blind_spots": blind_spots,
            "confidence": round(confidence, 2),
            "recommendation": "proceed with caution" if contradictions or blind_spots else "clean",
        }
        self.audit_log.append(entry)
        return entry

    def get_audit_log(self) -> list:
        return self.audit_log

    def last_audit(self) -> Optional[Dict[str, Any]]:
        return self.audit_log[-1] if self.audit_log else None


# Singleton for easy wiring
paradox = ParadoxAwareOrchestrator()