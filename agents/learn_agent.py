"""
Directed learning agent — user tells Prometheous *what* to learn.

Pipeline:
  1. Parse topic / curriculum command (list, queue, next, learn)
  2. Research via web search (+ optional brain knowledge hits)
  3. Write notes under data/learning/topics/
  4. Update curriculum.json
  5. Log trajectory for synthetic learning / finetune
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.config import cfg

    DATA = Path(cfg.DATA_DIR)
except Exception:
    DATA = Path(__file__).resolve().parents[1] / "data"


def _extract_topic(text: str) -> str:
    """Strip learn/study command wrappers from free text."""
    t = (text or "").strip()
    if not t:
        return ""
    patterns = [
        r"^/learn(?:ing)?\s+",
        r"^learn(?:ing)?\s+(?:about\s+)?",
        r"^study\s+(?:about\s+)?",
        r"^i\s+want\s+you\s+to\s+learn\s+(?:about\s+)?",
        r"^please\s+learn\s+(?:about\s+)?",
        r"^teach\s+yourself\s+(?:about\s+)?",
        r"^remember\s+to\s+learn\s+(?:about\s+)?",
        r"^you\s+should\s+learn\s+(?:about\s+)?",
        r"^figure\s+out\s+",
    ]
    for pat in patterns:
        t2 = re.sub(pat, "", t, count=1, flags=re.I).strip()
        if t2 != t:
            t = t2
            break
    # drop trailing politeness
    t = re.sub(r"\s+please\.?$", "", t, flags=re.I).strip()
    return t.strip(" .!?:")


class LearnAgent:
    name = "learn"
    role = "DirectedLearning"
    specialty = "User-directed curriculum: research topics → notes → memory"
    tasks_completed = 0

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        raw = str(
            payload.get("topic")
            or payload.get("goal")
            or payload.get("query")
            or payload.get("user_msg")
            or payload.get("target")
            or ""
        ).strip()
        mode = str(payload.get("mode") or "").lower().strip()

        # Explicit mode from gateway, or parse from text
        if not mode:
            mode, topic = self._parse_command(raw)
        else:
            topic = _extract_topic(raw) if mode in ("learn", "queue", "") else raw

        from learning.curriculum import curriculum

        if mode in ("list", "status", "show"):
            return {
                "status": "ok",
                "agent": self.name,
                "mode": "list",
                "formatted": curriculum.format_list(),
                "items": curriculum.list_brief(),
            }

        if mode == "queue":
            if not topic:
                return self._usage("queue needs a topic — e.g. /learn queue vector databases")
            item = curriculum.enqueue(topic, source="user", status="pending")
            return {
                "status": "ok",
                "agent": self.name,
                "mode": "queue",
                "item": item,
                "formatted": (
                    f"🟠 Queued for learning: **{item['topic']}**\n\n"
                    f"Status: pending\n"
                    f"Run `/learn next` or `/learn {item['topic']}` when you want me to study it."
                ),
            }

        if mode == "next":
            item = curriculum.next_pending()
            if not item:
                return {
                    "status": "ok",
                    "agent": self.name,
                    "mode": "next",
                    "formatted": (
                        "🟠 No pending topics.\n\n"
                        "Add some: /learn queue <topic> or /learn <topic>"
                    ),
                }
            topic = item["topic"]
            # fall through to learn

        if mode in ("learn", "study", "") or topic:
            if not topic:
                return self._usage()
            return self._learn_topic(topic, curriculum=curriculum, payload=payload)

        return self._usage()

    def _parse_command(self, raw: str) -> tuple[str, str]:
        text = (raw or "").strip()
        # strip leading /learn or learn
        rest = re.sub(r"^/learn(?:ing)?\s*", "", text, count=1, flags=re.I).strip()
        if rest == text:
            rest = re.sub(r"^learn(?:ing)?\s+", "", text, count=1, flags=re.I).strip()

        lower = rest.lower()
        if lower in ("list", "status", "show", "queue"):
            if lower == "queue":
                return "list", ""  # bare /learn queue → list with hint
            return lower if lower != "show" else "list", ""

        if lower.startswith("list"):
            return "list", ""
        if lower.startswith("status"):
            return "list", ""
        if lower.startswith("next"):
            return "next", ""
        if lower.startswith("queue "):
            return "queue", rest[6:].strip()
        if lower.startswith("study "):
            return "learn", rest[6:].strip()

        # natural language wrappers
        topic = _extract_topic(text)
        if topic.lower() in ("list", "status", "show"):
            return "list", ""
        if topic.lower() == "next":
            return "next", ""
        return "learn", topic

    def _learn_topic(self, topic: str, *, curriculum, payload: Dict[str, Any]) -> Dict[str, Any]:
        topic = topic.strip()
        curriculum.enqueue(topic, source=str(payload.get("source") or "user"), status="learning")
        curriculum.mark(topic, status="learning")

        steps: List[dict] = []
        sources: List[Dict[str, str]] = []
        brain_hits: List[Dict[str, Any]] = []
        snippets: List[str] = []

        # ── Web research ──
        try:
            from tools.web_search import search_web

            search = search_web(topic, num_results=int(payload.get("num_results") or 6))
            steps.append({"step": "web_search", "status": search.get("status") or "ok", "error": search.get("error")})
            for r in search.get("results") or []:
                sources.append({
                    "title": str(r.get("title") or "")[:200],
                    "url": str(r.get("url") or "")[:500],
                    "snippet": str(r.get("snippet") or "")[:400],
                })
                sn = (r.get("snippet") or "").strip()
                if sn:
                    snippets.append(sn)
        except Exception as e:
            steps.append({"step": "web_search_error", "error": str(e)[:200]})

        # ── Brain knowledge (existing abilities) ──
        try:
            from brain.knowledge_store import brain_knowledge

            brain_knowledge.load()
            hits = brain_knowledge.query(topic, top_k=5)
            brain_hits = hits if isinstance(hits, list) else []
            steps.append({"step": "brain_query", "hits": len(brain_hits)})
            for h in brain_hits[:3]:
                if isinstance(h, dict):
                    sn = h.get("snippet") or h.get("title") or ""
                    if sn:
                        snippets.append(str(sn)[:400])
                    if h.get("path"):
                        sources.append({
                            "title": f"brain:{h.get('title') or h.get('path')}",
                            "url": str(h.get("path")),
                            "snippet": str(h.get("snippet") or "")[:300],
                        })
        except Exception as e:
            steps.append({"step": "brain_error", "error": str(e)[:120]})

        # ── Optional: light GH/HF pointers (no full skill grow unless requested) ──
        grow = bool(payload.get("also_grow") or payload.get("grow"))
        grow_result: Optional[Dict[str, Any]] = None
        if grow:
            try:
                from agents.growth_agent import GrowthAgent

                grow_result = GrowthAgent().execute({"goal": topic, "pull_data": False})
                steps.append({"step": "growth", "status": grow_result.get("status")})
            except Exception as e:
                steps.append({"step": "growth_error", "error": str(e)[:120]})

        # ── Synthesize notes ──
        summary_lines = self._summarize(topic, snippets, sources, brain_hits)
        notes_body = "\n".join(summary_lines)
        notes_path = curriculum.write_notes(topic, notes_body, sources=sources)
        summary = summary_lines[0] if summary_lines else f"Learned overview of {topic}"
        if len(summary) > 200:
            summary = summary[:197] + "..."

        status = "learned" if (sources or brain_hits) else "failed"
        error = None if status == "learned" else "No sources found — try a more specific topic or check network"
        curriculum.mark(
            topic,
            status=status,
            summary=summary,
            notes_path=str(notes_path),
            sources=[{"title": s.get("title", ""), "url": s.get("url", "")} for s in sources[:10]],
            error=error,
        )

        # Trajectory
        try:
            traj = DATA / "learning" / "trajectories.jsonl"
            traj.parent.mkdir(parents=True, exist_ok=True)
            with open(traj, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "success": status == "learned",
                            "intent": "learn",
                            "agent": self.name,
                            "payload": {"topic": topic},
                            "result": {
                                "status": status,
                                "notes": str(notes_path),
                                "sources": len(sources),
                            },
                            "duration": 0,
                            "task_id": f"learn-{topic[:40]}",
                        }
                    )
                    + "\n"
                )
            steps.append({"step": "trajectory_logged"})
        except Exception:
            pass

        formatted = self._format(
            topic=topic,
            status=status,
            notes_path=notes_path,
            sources=sources,
            summary_lines=summary_lines,
            grow_result=grow_result,
            error=error,
        )
        return {
            "status": "ok" if status == "learned" else "failed",
            "agent": self.name,
            "mode": "learn",
            "topic": topic,
            "notes_path": str(notes_path),
            "sources": sources,
            "steps": steps,
            "formatted": formatted,
        }

    def _summarize(
        self,
        topic: str,
        snippets: List[str],
        sources: List[Dict[str, str]],
        brain_hits: List[Dict[str, Any]],
    ) -> List[str]:
        lines: List[str] = []
        if snippets:
            # Lead with first good snippet as summary line
            lines.append(f"{topic}: {snippets[0][:300]}")
            lines.append("")
            lines.append("Key points from research:")
            for i, sn in enumerate(snippets[:6], 1):
                lines.append(f"{i}. {sn[:350]}")
        else:
            lines.append(f"No live web snippets for «{topic}». Curriculum entry saved for retry.")
        if brain_hits:
            lines.append("")
            lines.append("Related brain knowledge:")
            for h in brain_hits[:4]:
                if not isinstance(h, dict):
                    continue
                title = h.get("title") or h.get("path") or "hit"
                sn = (h.get("snippet") or "")[:200]
                lines.append(f"- {title}: {sn}")
        if not sources and not brain_hits:
            lines.append("")
            lines.append("Next: refine the topic name, or use /grow <skill> for GitHub+HF skill packaging.")
        return lines

    def _format(
        self,
        *,
        topic: str,
        status: str,
        notes_path: Path,
        sources: List[Dict[str, str]],
        summary_lines: List[str],
        grow_result: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> str:
        icon = "✅" if status == "learned" else "❌"
        lines = [
            f"🟠 Learned: {topic}" if status == "learned" else f"🟠 Learning incomplete: {topic}",
            "",
            f"Status: {icon} {status}",
            f"Notes: {notes_path}",
            "",
        ]
        # first 8 lines of summary
        for ln in summary_lines[:10]:
            lines.append(ln)
        if sources:
            lines.append("")
            lines.append("Sources:")
            for s in sources[:5]:
                title = s.get("title") or s.get("url") or "source"
                url = s.get("url") or ""
                lines.append(f"  • {title}" + (f" — {url}" if url else ""))
        if grow_result:
            lines.append("")
            lines.append(f"Also grew skill: {grow_result.get('skill_name') or grow_result.get('status')}")
        if error:
            lines.append("")
            lines.append(f"Note: {error}")
        lines.append("")
        lines.append("Also: /learn list · /learn next · /grow <skill> for GitHub+HF packaging")
        return "\n".join(lines)[:4000]

    def _usage(self, hint: str = "") -> Dict[str, Any]:
        body = "\n".join([
            "🟠 Tell me what to learn",
            "",
            "Examples:",
            "• learn python asyncio",
            "• /learn graph rag retrieval",
            "• /learn queue kafka streams",
            "• /learn next",
            "• /learn list",
            "",
            "I research the topic, save notes under data/learning/topics/,",
            "and keep a curriculum so you can queue more for later.",
        ])
        if hint:
            body = hint + "\n\n" + body
        return {
            "status": "ok",
            "agent": self.name,
            "mode": "usage",
            "formatted": body,
        }

