# agents/agentgpt_agent.py
"""
Researcher tile (agentgpt). Now has real logic using wired components:
- tools controller for system/list
- core memory / knowledge for facts
- cognitive for constraints
- bus for events
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

try:
    from swarm.base import BaseAgent
except Exception:
    BaseAgent = object  # fallback


class AgentGPTAgent:
    """Researcher tile — synthesis + basic research using available system pieces."""

    name = "agentgpt"
    role = "AgentGPT"
    specialty = "research and synthesis"
    tasks_completed = 0

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed = getattr(self, "tasks_completed", 0) + 1
        query = (
            task.get("task")
            or task.get("user_msg")
            or task.get("goal")
            or task.get("query")
            or ""
        ).strip()
        if not query:
            query = "general research"

        findings = []
        used = []

        # Live web research when available
        try:
            from agents.web_search_agent import WebSearchAgent

            search = WebSearchAgent().execute(
                {"query": query, "user_msg": query, "num_results": 5}
            )
            if search.get("status") != "failed":
                findings.append(
                    {
                        "source": "web_search",
                        "data": (search.get("formatted") or "")[:800],
                    }
                )
                used.append("web_search")
        except Exception as e:
            findings.append({"source": "web_search", "error": str(e)[:120]})

        # Use tools (structured controller)
        if tools:
            try:
                sysinfo = tools.run("system_info")
                findings.append({"source": "tools.system_info", "data": sysinfo})
                used.append("tools")
            except Exception as e:
                findings.append({"source": "tools", "error": str(e)})

            try:
                listing = tools.run("list_directory", path=".")
                findings.append({"source": "tools.dir", "data": str(listing)[:300]})
                used.append("dir")
            except Exception:
                pass

        # Pull from knowledge (core memory)
        if knowledge:
            try:
                facts = knowledge.search("capability") or knowledge.search("fact") or []
                if facts:
                    findings.append({"source": "knowledge", "data": facts[:3]})
                    used.append("knowledge")
            except Exception:
                pass

        # Cognitive constraints if we can reach a base
        constraints = ""
        try:
            # Best effort - many agents now have it
            from brain.cognitive_loader import CognitiveLoader
            cl = CognitiveLoader()
            constraints = cl.get_constraints_string("researcher") or ""
            if constraints:
                used.append("cognitive")
        except Exception:
            pass

        # Publish via bus if possible
        try:
            from bus.agent_bus import bus
            bus.publish_sync("tile.research", {"query": query, "findings_count": len(findings)}, source="agentgpt")
        except Exception:
            pass

        synthesis = f"Researched '{query}'. Sources: {', '.join(used) or 'none'}. Findings: {len(findings)} items."

        return {
            "tile": "agentgpt",
            "agent": self.name,
            "status": "ok",
            "query": query,
            "synthesis": synthesis,
            "findings": findings,
            "used": used,
            "cognitive_constraints_used": bool(constraints),
            "message": synthesis,
            "formatted": "🔍 AgentGPT: " + synthesis,
        }