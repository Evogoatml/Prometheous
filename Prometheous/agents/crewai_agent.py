"""
CrewAI tile — multi-agent team coordinator.

Coordinates SuperAGI subtasks across AgentGPT, Agent K, Swarms, and other
registered specialists. This is the "crew" layer of the framework stack.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class CrewAISpecialist:
    """Team coordinator — assigns and runs specialists as a crew."""

    name = "crewai"
    role = "CrewAI"
    specialty = "multi-agent team coordination"
    tasks_completed = 0

    DEFAULT_TEAM = ["superagi", "agentgpt", "agentk", "swarms", "web_search", "task"]

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        query = (
            task.get("task")
            or task.get("user_msg")
            or task.get("goal")
            or task.get("query")
            or "general coordination"
        ).strip()

        team: List[str] = list(
            task.get("team")
            or self.DEFAULT_TEAM
        )
        # Always unique, preserve order
        seen = set()
        team = [t for t in team if not (t in seen or seen.add(t))]

        subtasks = task.get("subtasks") or []
        team_results: List[Dict[str, Any]] = []

        try:
            from core.orchestrator import orchestrator
        except Exception:
            orchestrator = None

        # 1) If SuperAGI is on the crew and no subtasks yet, decompose first
        if "superagi" in team and not subtasks and orchestrator:
            sag = orchestrator.get_agent("superagi")
            if sag and hasattr(sag, "execute"):
                try:
                    decomp = sag.execute({"task": query, "user_msg": query})
                    subtasks = list((decomp or {}).get("subtasks") or [])
                    team_results.append(
                        {
                            "member": "superagi",
                            "role": "decomposer",
                            "status": (decomp or {}).get("status"),
                            "subtasks": len(subtasks),
                        }
                    )
                except Exception as ex:
                    team_results.append({"member": "superagi", "error": str(ex)})

        # 2) Assign subtasks round-robin to crew members (skip pure meta roles if needed)
        executors = [m for m in team if m not in ("superagi",)] or team
        if subtasks and orchestrator:
            for i, st in enumerate(subtasks[:24]):
                member = executors[i % len(executors)]
                desc = (
                    st.get("description")
                    if isinstance(st, dict)
                    else str(st)
                )
                preferred = (
                    (st.get("agent") if isinstance(st, dict) else None) or member
                )
                # map common labels
                preferred = {
                    "recon": "agentgpt",
                    "research": "agentgpt",
                    "report": "agentgpt",
                    "scan": "scanner",
                    "code": "agentk",
                    "exploit": "agentk",
                    "skill": "agentk",
                }.get(str(preferred).lower(), preferred)

                agent = orchestrator.get_agent(str(preferred)) or orchestrator.get_agent(member)
                if agent is None or not hasattr(agent, "execute"):
                    team_results.append(
                        {
                            "member": preferred,
                            "subtask": desc,
                            "status": "skipped",
                            "error": "agent missing",
                        }
                    )
                    continue
                try:
                    sub = agent.execute(
                        {
                            "user_msg": desc,
                            "task": desc,
                            "goal": desc,
                            "crewai": True,
                            "parent_goal": query,
                        }
                    )
                    team_results.append(
                        {
                            "member": getattr(agent, "name", preferred),
                            "subtask": str(desc)[:120],
                            "status": (sub or {}).get("status", "ok"),
                            "preview": str(
                                (sub or {}).get("formatted")
                                or (sub or {}).get("message")
                                or ""
                            )[:160],
                        }
                    )
                except Exception as ex:
                    team_results.append(
                        {
                            "member": preferred,
                            "subtask": str(desc)[:120],
                            "error": str(ex),
                            "status": "failed",
                        }
                    )
        elif orchestrator:
            # No subtasks — ping each crew member once with the full goal
            for member in executors[:6]:
                agent = orchestrator.get_agent(member)
                if agent is None or not hasattr(agent, "execute"):
                    team_results.append(
                        {"member": member, "status": "skipped", "error": "missing"}
                    )
                    continue
                try:
                    sub = agent.execute(
                        {
                            "user_msg": f"[crewai] {query}",
                            "task": query,
                            "goal": query,
                            "crewai": True,
                        }
                    )
                    team_results.append(
                        {
                            "member": member,
                            "status": (sub or {}).get("status", "ok"),
                            "preview": str(
                                (sub or {}).get("formatted")
                                or (sub or {}).get("message")
                                or ""
                            )[:160],
                        }
                    )
                except Exception as ex:
                    team_results.append(
                        {"member": member, "status": "failed", "error": str(ex)}
                    )

        try:
            from bus.agent_bus import bus

            bus.publish_sync(
                "tile.crewai",
                {
                    "query": query[:200],
                    "team_size": len(team),
                    "results": len(team_results),
                },
                source="crewai",
            )
        except Exception:
            pass

        ok_n = sum(1 for r in team_results if r.get("status") in ("ok", "done", None) and not r.get("error"))
        message = (
            f"CrewAI coordinated {len(team)} specialists "
            f"({ok_n}/{len(team_results)} assignments ok) for: {query[:80]}"
        )
        return {
            "tile": "crewai",
            "agent": self.name,
            "status": "ok",
            "query": query,
            "team": team,
            "subtasks": subtasks,
            "team_results": team_results,
            "message": message,
            "formatted": message
            + "\n"
            + "\n".join(
                f"  • {r.get('member')}: {r.get('status')} {r.get('preview') or r.get('error') or ''}"[:120]
                for r in team_results[:10]
            ),
        }
