"""
User-directed learning curriculum.

The user tells Prometheous *what* to learn; this module persists the queue
and learned topic notes under data/learning/.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.config import cfg

    DATA = Path(cfg.DATA_DIR)
except Exception:
    DATA = Path(__file__).resolve().parents[1] / "data"

LEARNING_DIR = DATA / "learning"
CURRICULUM_PATH = LEARNING_DIR / "curriculum.json"
TOPICS_DIR = LEARNING_DIR / "topics"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(topic: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", topic.lower())
    base = "_".join(words[:8]) if words else "topic"
    return base[:60]


class Curriculum:
    """Persistent queue of topics the user wants the agent to learn."""

    def __init__(self, path: Path | None = None, topics_dir: Path | None = None):
        self.path = path or CURRICULUM_PATH
        self.topics_dir = topics_dir or TOPICS_DIR
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.topics_dir.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.path.is_file():
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "items" in data:
                    return data
            except Exception:
                pass
        return {"version": 1, "items": [], "updated_at": _now_iso()}

    def _save(self) -> None:
        self._data["updated_at"] = _now_iso()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    @property
    def items(self) -> List[Dict[str, Any]]:
        return list(self._data.get("items") or [])

    def find(self, topic: str) -> Optional[Dict[str, Any]]:
        key = topic.strip().lower()
        slug = _slug(topic)
        for item in self.items:
            if item.get("topic", "").lower() == key or item.get("slug") == slug:
                return item
        return None

    def enqueue(
        self,
        topic: str,
        *,
        priority: int = 0,
        source: str = "user",
        status: str = "pending",
    ) -> Dict[str, Any]:
        topic = topic.strip()
        if not topic:
            raise ValueError("empty topic")
        existing = self.find(topic)
        if existing:
            existing["priority"] = max(int(existing.get("priority") or 0), priority)
            if status == "pending" and existing.get("status") == "learned":
                # re-queue already-learned topic if user asks again
                existing["status"] = "pending"
                existing["requested_at"] = _now_iso()
            existing["updated_at"] = _now_iso()
            self._save()
            return existing

        item = {
            "id": f"learn-{int(time.time() * 1000)}",
            "topic": topic,
            "slug": _slug(topic),
            "status": status,  # pending | learning | learned | failed
            "priority": priority,
            "source": source,
            "requested_at": _now_iso(),
            "updated_at": _now_iso(),
            "learned_at": None,
            "notes_path": None,
            "summary": None,
            "sources": [],
            "error": None,
        }
        self._data.setdefault("items", []).append(item)
        self._save()
        return item

    def mark(
        self,
        topic: str,
        *,
        status: str,
        summary: str | None = None,
        notes_path: str | None = None,
        sources: List[Dict[str, str]] | None = None,
        error: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        item = self.find(topic)
        if item is None:
            item = self.enqueue(topic, status=status)
        item["status"] = status
        item["updated_at"] = _now_iso()
        if summary is not None:
            item["summary"] = summary[:2000]
        if notes_path is not None:
            item["notes_path"] = notes_path
        if sources is not None:
            item["sources"] = sources
        if error is not None:
            item["error"] = error[:500]
        if status == "learned":
            item["learned_at"] = _now_iso()
        self._save()
        return item

    def next_pending(self) -> Optional[Dict[str, Any]]:
        pending = [i for i in self.items if i.get("status") == "pending"]
        if not pending:
            return None
        pending.sort(key=lambda x: (-int(x.get("priority") or 0), x.get("requested_at") or ""))
        return pending[0]

    def list_brief(self, *, limit: int = 30) -> List[Dict[str, Any]]:
        items = sorted(
            self.items,
            key=lambda x: (
                0 if x.get("status") == "pending" else 1,
                -int(x.get("priority") or 0),
                x.get("requested_at") or "",
            ),
        )
        return items[:limit]

    def write_notes(
        self,
        topic: str,
        body: str,
        *,
        sources: List[Dict[str, str]] | None = None,
    ) -> Path:
        slug = _slug(topic)
        path = self.topics_dir / f"{slug}.md"
        header = [
            f"# Learned: {topic}",
            "",
            f"_Updated: {_now_iso()}_",
            "",
        ]
        if sources:
            header.append("## Sources")
            header.append("")
            for s in sources[:12]:
                title = s.get("title") or s.get("url") or "source"
                url = s.get("url") or ""
                header.append(f"- [{title}]({url})" if url else f"- {title}")
            header.append("")
            header.append("## Notes")
            header.append("")
        path.write_text("\n".join(header) + body.strip() + "\n", encoding="utf-8")
        return path

    def format_list(self) -> str:
        items = self.list_brief()
        if not items:
            return (
                "🟠 Learning curriculum is empty.\n\n"
                "Tell me what to learn:\n"
                "• learn python asyncio\n"
                "• /learn graph rag\n"
                "• /learn queue kubernetes memory\n"
            )
        lines = ["🟠 Learning curriculum", ""]
        counts: Dict[str, int] = {}
        for i in items:
            st = i.get("status") or "?"
            counts[st] = counts.get(st, 0) + 1
        lines.append(
            "Status: "
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        )
        lines.append("")
        for i in items:
            icon = {
                "pending": "⏳",
                "learning": "🔄",
                "learned": "✅",
                "failed": "❌",
            }.get(i.get("status") or "", "•")
            topic = i.get("topic") or "?"
            summary = (i.get("summary") or "").strip()
            extra = f" — {summary[:80]}" if summary else ""
            lines.append(f"{icon} {topic}{extra}")
            if i.get("notes_path"):
                lines.append(f"   notes: {i['notes_path']}")
        lines.append("")
        lines.append("Commands: /learn <topic> · /learn list · /learn next · /learn queue <topic>")
        return "\n".join(lines)


# Module-level singleton used by agents/gateway
curriculum = Curriculum()

