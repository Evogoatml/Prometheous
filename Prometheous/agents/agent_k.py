# agents/agent_k.py
"""
AgentK tile — skill / code / ops specialist.
Uses tools + knowledge for actual work.
"""
from typing import Dict, Any

try:
    from controllers.tool_controller import tools
except Exception:
    tools = None

try:
    from core.memory import knowledge
except Exception:
    knowledge = None


class AgentKExecutor:
    """Skill specialist tile — code, crypto, system operations using live pieces."""

    name = "agentk"
    role = "AgentK"
    specialty = "skills, code, ops"
    tasks_completed = 0

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed = getattr(self, "tasks_completed", 0) + 1
        query = (
            task.get("task")
            or task.get("user_msg")
            or task.get("goal")
            or task.get("query")
            or ""
        ).strip() or "system skill task"

        ops = []
        if tools:
            try:
                ops.append({"op": "hash", "result": tools.run("hash", text=query, algorithm="sha256")})
                ops.append({"op": "sysinfo", "result": tools.run("system_info")})
            except Exception as e:
                ops.append({"op": "tools_error", "detail": str(e)})

        if knowledge:
            try:
                caps = knowledge.search("capability") or []
                if caps:
                    ops.append({"op": "knowledge_caps", "sample": caps[:2]})
            except Exception:
                pass

        msg = f"AgentK executed {len(ops)} skill ops for: {query[:60]}"
        return {
            "tile": "agentk",
            "agent": self.name,
            "status": "ok",
            "query": query,
            "operations": ops,
            "message": msg,
            "formatted": msg,
        }