"""Format paradox audit results for Telegram / chat."""
from __future__ import annotations

from typing import Any, Dict, List


def format_paradox_audit(result: Dict[str, Any]) -> str:
    audit = result.get("result") or result
    if not isinstance(audit, dict):
        return str(audit)

    if audit.get("note") == "paradox auditor not available":
        return "Paradox auditor is not loaded."

    mode = audit.get("mode", "task")
    lines: List[str] = ["🛡 Prometheous Paradox Audit"]

    if mode == "self":
        lines.append("_Independent system report — not LLM self-testimony_")
        lines.append("")

    query = audit.get("query", "")
    if query:
        lines.append(f"Subject: {query[:120]}")
        lines.append("")

    strengths = audit.get("strengths") or []
    if strengths:
        lines.append("✅ Strengths")
        lines.extend(f"• {s}" for s in strengths)
        lines.append("")

    limitations = audit.get("limitations") or []
    if limitations:
        lines.append("⚠️ Known limitations")
        lines.extend(f"• {l}" for l in limitations)
        lines.append("")

    contradictions = audit.get("contradictions") or []
    if contradictions:
        lines.append("⚡ Contradictions")
        lines.extend(f"• {c}" for c in contradictions)
        lines.append("")

    blind = audit.get("blind_spots") or []
    if blind:
        lines.append("🔍 Blind spots")
        lines.extend(f"• {b}" for b in blind)
        lines.append("")

    paradox_note = audit.get("paradox_note")
    if paradox_note:
        lines.append("🎯 Structural note")
        lines.append(paradox_note)
        lines.append("")

    rec = audit.get("recommendation", "unknown")
    lines.append(f"Recommendation: **{rec}**")

    agents = audit.get("registered_agents") or []
    if agents:
        lines.append(f"Agents online: {', '.join(agents[:12])}")

    return "\n".join(lines).strip()