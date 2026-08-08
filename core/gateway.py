"""
Message gateway — channel-agnostic routing for Prometheous.

Telegram (and other transports) are bridges: they deliver text here and
send back the reply. Commands, decision engine, orchestrator, and LLM
phrasing all live in this module.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from swarm.commands import (
    PROMPT,
    IDENTITY_REPLY,
    command_head,
    format_abilities_text,
    format_agents_text,
    format_commands_text,
    format_welcome_text,
    is_abilities_request,
    is_commands_request,
    is_context_request,
    is_identity_request,
    is_improve_request,
    resolve_context_reply,
)

logger = logging.getLogger(__name__)

MAX_REPLY_LEN = 4000


@dataclass
class GatewayResult:
    """Outcome of processing one inbound user message."""

    handled: bool = False
    reply: Optional[str] = None
    intent: str = ""
    agent: Optional[str] = None


class MessageGateway:
    """Route user text through commands, decision engine, and orchestrator."""

    def handle(self, text: str, *, context: Optional[Dict[str, Any]] = None) -> GatewayResult:
        """
        Process one message. Returns handled=True when no further processing
        is needed (reply may be None for silent command handling).
        """
        ctx = context or {}
        text = (text or "").strip()
        if not text:
            return GatewayResult(handled=True, reply="")

        cmd_result = self._try_command(text, ctx)
        if cmd_result is not None:
            self._persist_turn(ctx, text, cmd_result)
            return cmd_result

        reply, meta = self._handle_natural(text, ctx)
        result = GatewayResult(
            handled=True,
            reply=reply,
            intent=meta.get("intent", ""),
            agent=meta.get("agent"),
        )
        self._persist_turn(ctx, text, result)
        return result

    def handle_for_test(self, text: str, *, context: Optional[Dict[str, Any]] = None) -> str:
        """Convenience for break-in: returns reply text only."""
        result = self.handle(text, context=context)
        return result.reply or ""

    # ------------------------------------------------------------------
    def _chat_id(self, ctx: Dict[str, Any]) -> int:
        raw = ctx.get("chat_id", 0)
        if raw is None or raw == "":
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _decision_context(self, ctx: Dict[str, Any], text: str) -> Dict[str, Any]:
        return {"target": text, "chat_id": self._chat_id(ctx)}

    def _history(self, ctx: Dict[str, Any], limit: int = 12) -> list:
        """Recent turns for multi-turn conversation (excludes the message being processed)."""
        try:
            from memory.persistent import store as persistent_store

            mem = persistent_store.get(self._chat_id(ctx))
            return mem.get_history(limit=limit)
        except Exception:
            return []

    def _user_name(self, ctx: Dict[str, Any]) -> Optional[str]:
        try:
            from memory.user_prefs import get_prefs

            prefs = get_prefs(self._chat_id(ctx))
            name = prefs.get("name")
            return str(name) if name else None
        except Exception:
            return None

    def _llm_respond(
        self,
        output: Dict[str, Any],
        text: str,
        ctx: Dict[str, Any],
        *,
        history: Optional[list] = None,
    ) -> str:
        """Phrase a reply with conversation memory when the LLM is available."""
        from llm.client import llm

        so = dict(output or {})
        name = self._user_name(ctx)
        if name and "user_name" not in so:
            so["user_name"] = name
        hist = history if history is not None else self._history(ctx)
        return llm.respond(so, text, history=hist)

    def _persist_turn(self, ctx: Dict[str, Any], user_text: str, result: GatewayResult) -> None:
        chat_id = self._chat_id(ctx)
        if not result.reply:
            return
        try:
            from memory.persistent import store as persistent_store
            from memory.user_prefs import record_turn

            mem = persistent_store.get(chat_id)
            mem.add(
                "user",
                user_text,
                metadata={
                    "intent": result.intent or "command",
                    "agent": result.agent,
                    "channel": ctx.get("channel", ""),
                },
            )
            mem.add(
                "assistant",
                result.reply[:MAX_REPLY_LEN],
                metadata={"intent": result.intent or "command", "agent": result.agent},
            )
            record_turn(chat_id, result.intent or "command", result.agent)
        except Exception:
            logger.debug("gateway persist_turn failed", exc_info=True)

    def _try_command(self, text: str, ctx: Dict[str, Any]) -> Optional[GatewayResult]:
        command = command_head(text)

        if is_commands_request(text):
            return GatewayResult(handled=True, reply=format_commands_text(), intent="commands")
        if command in {"/start", "/help"}:
            return GatewayResult(handled=True, reply=format_welcome_text(), intent="welcome")
        if command in {"/abilities", "/capabilities"}:
            return GatewayResult(handled=True, reply=self._abilities_text(), intent="abilities")
        if is_identity_request(text):
            return GatewayResult(handled=True, reply=IDENTITY_REPLY, intent="identity")
        # Improve requests must ACT (growth agent), not return a how-to lecture.
        if is_improve_request(text):
            return GatewayResult(
                handled=True,
                reply=self._route_growth(text),
                intent="growth",
                agent="growth",
            )
        if is_abilities_request(text):
            return GatewayResult(handled=True, reply=self._abilities_text(), intent="abilities")
        if command in {"/reflect", "/audit", "/paradox"} or command.startswith("/audit "):
            return GatewayResult(handled=True, reply=self._route_paradox(text), intent="reflect", agent="paradox")
        if command.startswith("/search") or command.startswith("search "):
            return GatewayResult(handled=True, reply=self._route_web_search(text), intent="web_search", agent="web_search")
        if command.startswith("/ads") or command in {"/ad", "/campaign", "/shopify_ads"}:
            return GatewayResult(handled=True, reply=self._route_shopify_ads(text), intent="shopify_ads", agent="shopify_ads")
        if command.startswith("/learn") or command.startswith("/learning"):
            return GatewayResult(handled=True, reply=self._route_learn(text), intent="learn", agent="learn")
        if command.startswith("/grow") or command in {"/growth", "/selfgrow", "/evolve"}:
            return GatewayResult(handled=True, reply=self._route_growth(text), intent="growth", agent="growth")
        if command.startswith("/mission") or command in {"/do", "/mission_run"}:
            return GatewayResult(
                handled=True,
                reply=self._route_mission(text),
                intent="mission",
                agent="mission",
            )
        if command.startswith("/mosaic") or command in {"/polymorphic", "/assemble"}:
            return GatewayResult(
                handled=True,
                reply=self._route_mosaic(text),
                intent="mosaic",
                agent="mosaic",
            )
        if command.startswith("/sentinel") or text.strip().lower().startswith("sentinel "):
            return self._route_sentinel(text)
        if command == "/agents":
            return GatewayResult(handled=True, reply=self._agents_text(), intent="agents")
        if command.startswith("/context"):
            return GatewayResult(handled=True, reply=self._route_folder_context(text), intent="context")
        if command.startswith("/heal"):
            return GatewayResult(handled=True, reply=self._route_heal(text), intent="heal")
        if command.startswith("/tool"):
            return GatewayResult(handled=True, reply=self._route_tool_call(text, ctx), intent="call_tool", agent="mcp_tools")
        if command == "/status":
            return GatewayResult(handled=True, reply=self._status_text(ctx), intent="status")

        return None

    def _handle_natural(self, text: str, ctx: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        logger.info("gateway incoming: text=%r", text[:140])

        if is_commands_request(text):
            return format_commands_text(), {"intent": "commands"}
        if is_context_request(text):
            return self._route_folder_context(text), {"intent": "context"}
        # Note: "improve yourself" is NOT short-circuited — decision routes to growth agent

        try:
            from core.decision import Decision, engine as decision_engine
            from core.orchestrator import orchestrator
            from llm.client import llm
        except Exception as exc:
            logger.error("gateway import failed: %s", exc)
            return f"Error: {exc}", {"intent": "error"}

        context_snippet = self._rag_snippet(text)
        dctx = self._decision_context(ctx, text)
        # Load history once per turn so multi-turn chat has context
        history = self._history(ctx)

        try:
            decision = decision_engine.decide(text, context=dctx)
        except Exception as exc:
            logger.error("gateway decision error: %s", exc)
            return f"Error: {exc}", {"intent": "error"}

        forced = self._forced_agent(text) if self._force_agent_enabled() else None
        if forced and decision.agent != forced and decision.action in ("dispatch", "respond", "reflect"):
            decision = Decision(
                action="dispatch",
                agent=forced,
                target=decision.target or text,
                reason=f"{decision.reason}; forced_agent={forced}",
                confidence=decision.confidence,
            )

        meta = {"intent": decision.action, "agent": decision.agent}
        reply = ""
        try:
            if decision.action == "respond":
                reason = (decision.reason or "").lower()
                if "identity" in reason:
                    reply = IDENTITY_REPLY
                elif "abilities" in reason:
                    reply = self._abilities_text()
                elif "commands" in reason:
                    reply = format_commands_text()
                elif "status" in reason:
                    reply = self._status_text(ctx)
                elif "agents" in reason:
                    reply = self._agents_text()
                elif reason in ("greet", "chat") or "greet" in reason or reason == "chat":
                    # Real conversation — history-aware, human voice
                    mode = "greet" if "greet" in reason else "chat"
                    output = {
                        "intent": mode,
                        "mode": mode,
                        "reason": decision.reason,
                    }
                    if context_snippet and mode == "chat":
                        output["context"] = context_snippet
                    reply = self._llm_respond(output, text, ctx, history=history)
                else:
                    output = {
                        "intent": "chat",
                        "mode": "chat",
                        "reason": decision.reason,
                    }
                    if context_snippet:
                        output["context"] = context_snippet
                    reply = self._llm_respond(output, text, ctx, history=history)
            elif decision.action == "call_tool":
                task = orchestrator.dispatch(decision, {"user_msg": text, "chat_id": self._chat_id(ctx)})
                if isinstance(task.result, dict):
                    reply = (
                        task.result.get("formatted")
                        or task.result.get("error")
                        or "That tool call didn't work — want me to try another way?"
                    )
                else:
                    reply = "That tool call didn't work — want me to try another way?"
            elif decision.action in ("create_skill", "run_skill"):
                task = orchestrator.dispatch(decision, {"user_msg": text, "chat_id": self._chat_id(ctx)})
                payload = task.result or {"status": task.status, "error": task.error}
                # Prefer agent-formatted text; only phrase when we have raw structure
                if isinstance(payload, dict) and payload.get("formatted"):
                    reply = payload["formatted"]
                else:
                    so = payload if isinstance(payload, dict) else {"result": payload}
                    if isinstance(so, dict):
                        so = {**so, "mode": "phrase"}
                    reply = self._llm_respond(so, text, ctx, history=history)
            elif decision.action == "dispatch" and decision.agent:
                task = orchestrator.dispatch(decision, {
                    "user_msg": text,
                    "query": decision.target or text,
                    "chat_id": self._chat_id(ctx),
                })
                # Trust specialist formatted output — it's already humanized.
                # Don't LLM-rewrite work results (that invents denials / loses facts).
                if decision.agent == "web_search" and isinstance(task.result, dict):
                    reply = task.result.get("formatted") or task.result.get("error") or "Nothing useful came back."
                elif decision.agent == "shopify_ads" and isinstance(task.result, dict):
                    reply = task.result.get("formatted") or task.result.get("error") or "Ad campaign finished."
                elif decision.agent == "task" and isinstance(task.result, dict):
                    reply = task.result.get("formatted") or task.result.get("error") or "I tried — want me to push further?"
                elif decision.agent == "knowledge" and isinstance(task.result, dict):
                    reply = task.result.get("formatted") or task.result.get("error") or "Knowledge lookup done."
                elif decision.agent == "mission" and isinstance(task.result, dict):
                    reply = task.result.get("formatted") or task.result.get("error") or "Mission finished."
                elif decision.agent == "mosaic" and isinstance(task.result, dict):
                    reply = task.result.get("formatted") or task.result.get("error") or "Mosaic finished."
                elif decision.agent == "growth" and isinstance(task.result, dict):
                    reply = task.result.get("formatted") or task.result.get("error") or "Growth finished."
                elif decision.agent == "learn" and isinstance(task.result, dict):
                    reply = task.result.get("formatted") or task.result.get("error") or "Learning finished."
                elif decision.agent == "paradox" and isinstance(task.result, dict):
                    from agents.paradox_format import format_paradox_audit
                    reply = task.result.get("formatted") or format_paradox_audit(task.result)
                elif isinstance(task.result, dict) and task.result.get("formatted"):
                    reply = task.result["formatted"]
                else:
                    output = {
                        "intent": decision.action,
                        "mode": "phrase",
                        "agent": decision.agent,
                        "status": task.status,
                        "result": task.result,
                        "reason": decision.reason,
                    }
                    if context_snippet:
                        output["context"] = context_snippet
                    reply = self._llm_respond(output, text, ctx, history=history)
            else:
                output = {
                    "intent": decision.action or "chat",
                    "mode": "chat",
                    "agent": decision.agent,
                    "reason": decision.reason,
                }
                if context_snippet:
                    output["context"] = context_snippet
                reply = self._llm_respond(output, text, ctx, history=history)
        except Exception as exc:
            logger.error("gateway dispatch/respond error: %s", exc)
            reply = f"Something went wrong on my side: {exc}"

        if not reply:
            reply = "I'm here — say that again, or tell me what you want done."
        logger.info("gateway reply: len=%d reply=%r", len(reply), reply[:160])
        return reply[:MAX_REPLY_LEN], meta

    def _force_agent_enabled(self) -> bool:
        return os.getenv("PROM_GATEWAY_FORCE_AGENT", "").lower() in ("1", "true", "yes")

    def _forced_agent(self, text: str) -> Optional[str]:
        """Optional explicit dispatch — disabled unless PROM_GATEWAY_FORCE_AGENT=1."""
        try:
            from core.orchestrator import orchestrator
            registered = [n for n in orchestrator.list_agents() if n != "telegram"]
        except Exception:
            return None

        raw = (text or "").strip()
        direct = re.match(r"^(?:use|dispatch|call)\s+([\w.-]+)\b", raw, re.I)
        if direct:
            name = direct.group(1).lower().replace("-", "_")
            if name in registered:
                return name
        return None

    # ------------------------------------------------------------------
    def _abilities_text(self) -> str:
        from core.orchestrator import orchestrator

        try:
            agents = sorted(orchestrator.list_agents())
        except Exception:
            agents = []
        return format_abilities_text(agents)

    def _agents_text(self) -> str:
        from core.orchestrator import orchestrator

        try:
            names = sorted(orchestrator.list_agents())
        except Exception:
            names = []
        return format_agents_text(names)

    def _status_text(self, ctx: Dict[str, Any]) -> str:
        from core.orchestrator import orchestrator

        gateway_active = bool(ctx.get("gateway_active", False))
        agents: list[str] = []
        try:
            agents = [n for n in orchestrator.list_agents() if n != "telegram"]
        except Exception:
            pass
        llm_on = os.getenv("PROM_TELEGRAM_LLM", "").lower() in ("1", "true", "yes")
        gs = orchestrator.get_agent("ghost_sentinel")
        gs_tools: list[str] = []
        if gs is not None:
            try:
                gs_tools = list(getattr(gs, "swarm", None) and gs.swarm.registry.list_registered() or [])
            except Exception:
                pass
        lines = [
            f"I'm up — {PROMPT}.",
            f"Gateway: {'running' if gateway_active else 'idle'}",
            f"Agents loaded: {len(agents)}",
            f"Natural replies: {'on' if llm_on else 'off (template mode)'}",
            f"Ghost Sentinel tools: {len(gs_tools)}",
            "",
            "Just talk to me, or ask for /commands if you want the shortcuts.",
        ]
        return "\n".join(lines)

    def _route_paradox(self, text: str) -> str:
        from core.orchestrator import orchestrator

        agent = orchestrator.get_agent("paradox")
        if agent is None:
            return "Paradox auditor is not registered."

        mode = "self" if any(
            t in text.lower()
            for t in ("self-audit", "self audit", "audit yourself", "/audit", "/reflect", "/paradox")
        ) else "task"

        result = agent.execute({"user_msg": text, "mode": mode})
        reply = result.get("formatted") or result.get("message") or "Audit complete."
        return reply[:MAX_REPLY_LEN]

    def _route_web_search(self, text: str) -> str:
        from core.orchestrator import orchestrator

        agent = orchestrator.get_agent("web_search")
        if agent is None:
            return "Web search agent is not registered."

        query = text.strip()
        for prefix in ("/search", "search"):
            if query.lower().startswith(prefix):
                query = query[len(prefix):].strip()
                break
        if not query:
            return "Usage: /search <your question>\nExample: /search latest AI news"

        result = agent.execute({"query": query, "user_msg": text})
        reply = result.get("formatted") or result.get("error") or "Search failed."
        return reply[:MAX_REPLY_LEN]

    def _route_shopify_ads(self, text: str) -> str:
        """Run ads pipeline immediately — no questionnaire, no 'I can't'."""
        from core.orchestrator import orchestrator

        agent = orchestrator.get_agent("shopify_ads")
        if agent is None:
            # Lazy register if bootstrap missed it
            try:
                from agents.shopify_ads_agent import ShopifyAdsAgent
                agent = ShopifyAdsAgent()
                orchestrator.register_agent(agent.name, agent)
            except Exception as exc:
                return f"Ads agent unavailable: {exc}"

        mode = None
        lower = text.lower()
        if "launch" in lower or "publish" in lower or "go live" in lower:
            mode = "launch"
        elif "dry" in lower or "package only" in lower:
            mode = "dry_run"

        result = agent.execute({"user_msg": text, "mode": mode, "query": text})
        reply = result.get("formatted") or result.get("error") or "Ad campaign finished."
        return reply[:MAX_REPLY_LEN]

    def _route_learn(self, text: str) -> str:
        """User-directed learning: research topic → notes + curriculum."""
        from core.orchestrator import orchestrator

        agent = orchestrator.get_agent("learn")
        if agent is None:
            try:
                from agents.learn_agent import LearnAgent
                agent = LearnAgent()
                orchestrator.register_agent(agent.name, agent)
            except Exception as exc:
                return f"Learn agent unavailable: {exc}"

        result = agent.execute({"user_msg": text, "query": text, "topic": text})
        reply = result.get("formatted") or result.get("error") or "Learning finished."
        return reply[:MAX_REPLY_LEN]

    def _route_growth(self, text: str) -> str:
        """GitHub + HuggingFace research → skill synthesis (self-growth)."""
        from core.orchestrator import orchestrator

        agent = orchestrator.get_agent("growth")
        if agent is None:
            try:
                from agents.growth_agent import GrowthAgent
                agent = GrowthAgent()
                orchestrator.register_agent(agent.name, agent)
            except Exception as exc:
                return f"Growth agent unavailable: {exc}"

        goal = text.strip()
        for prefix in ("/grow", "/growth", "/selfgrow", "/evolve", "grow"):
            if goal.lower().startswith(prefix):
                goal = goal[len(prefix):].strip()
                break
        if not goal:
            goal = "agent tools memory reasoning language:python"

        result = agent.execute({"goal": goal, "user_msg": text, "query": goal})
        reply = result.get("formatted") or result.get("error") or "Growth finished."
        return reply[:MAX_REPLY_LEN]

    def _route_mission(self, text: str) -> str:
        """Plan → write code → deploy agents → execute until done."""
        from core.orchestrator import orchestrator

        agent = orchestrator.get_agent("mission")
        if agent is None:
            try:
                from agents.mission_agent import MissionAgent

                agent = MissionAgent()
                orchestrator.register_agent(agent.name, agent)
            except Exception as exc:
                return f"Mission conductor unavailable: {exc}"

        goal = text.strip()
        for prefix in ("/mission", "/do", "mission"):
            if goal.lower().startswith(prefix):
                goal = goal[len(prefix) :].strip(" :-\t")
                break
        if not goal:
            return (
                "Usage: /mission <task>\n"
                "Example: /mission deploy a checklist bot that prints launch steps\n\n"
                "I will plan, write code, deploy agents, and run them."
            )

        result = agent.execute({"goal": goal, "user_msg": text, "query": goal})
        reply = result.get("formatted") or result.get("error") or "Mission finished."
        return reply[:MAX_REPLY_LEN]

    def _route_mosaic(self, text: str) -> str:
        """Polymorphic auto-mosaic: assemble tiles → act → adapt → synthesize."""
        from core.orchestrator import orchestrator

        agent = orchestrator.get_agent("mosaic")
        if agent is None:
            try:
                from agents.mosaic_agent import MosaicAgent

                agent = MosaicAgent()
                orchestrator.register_agent(agent.name, agent)
            except Exception as exc:
                return f"Mosaic unavailable: {exc}"

        goal = text.strip()
        for prefix in ("/mosaic", "/polymorphic", "/assemble", "mosaic"):
            if goal.lower().startswith(prefix):
                goal = goal[len(prefix) :].strip()
                break
        if not goal:
            goal = "assemble research and code tiles to improve autonomous task execution"

        result = agent.execute({"goal": goal, "user_msg": text, "query": goal})
        reply = result.get("formatted") or result.get("error") or "Mosaic finished."
        return reply[:MAX_REPLY_LEN]

    def _route_tool_call(self, text: str, ctx: Dict[str, Any]) -> str:
        from core.decision import engine as decision_engine
        from core.orchestrator import orchestrator

        if command_head(text) == "/tool" and text.strip() == "/tool":
            return (
                "Usage: /tool <name> key=value …\n"
                "Example: /tool fs.read path=main.py\n\n"
                "Natural language also works: fetch https://…, read file main.py"
            )

        decision = decision_engine.decide(text, context=self._decision_context(ctx, text))
        if decision.action != "call_tool":
            return (
                f"No tool matched. Decision: {decision.action} ({decision.reason})\n"
                "Try: /tool ping  or  read file main.py"
            )

        task = orchestrator.dispatch(decision, {"user_msg": text, "chat_id": self._chat_id(ctx)})
        result = task.result if isinstance(task.result, dict) else {}
        reply = result.get("formatted") or result.get("error") or f"Tool {decision.tool_name} failed."
        return reply[:MAX_REPLY_LEN]

    def _route_heal(self, text: str) -> str:
        parts = text.strip().split()
        cmd = command_head(text)

        if cmd == "/heal" and len(parts) == 1:
            from learning.healing import list_proposals_brief
            return list_proposals_brief(limit=5)

        if len(parts) >= 3 and parts[1] == "show":
            from learning.healing import format_proposal_brief
            from learning.healing.proposal_log import ProposalLog
            entry = ProposalLog().get(parts[2])
            if not entry:
                return f"Unknown proposal: {parts[2]}"
            body = format_proposal_brief(entry)
            best = (entry.get("proposals") or [{}])[0]
            if best.get("diff"):
                body += f"\n\n```\n{best['diff'][:2500]}\n```"
            return body[:MAX_REPLY_LEN]

        if len(parts) >= 3 and parts[1] == "apply":
            from learning.healing import apply_worktree
            result = apply_worktree(parts[2])
            if result.get("status") == "ok":
                return (
                    f"Worktree apply OK\n"
                    f"ID: {parts[2]}\n"
                    f"Path: {result.get('worktree_path')}\n"
                    f"Compile: {result.get('compile_msg')}"
                )
            return f"Apply failed: {result.get('error', result)}"

        if len(parts) >= 3 and parts[1] == "live":
            from learning.healing import apply_live
            result = apply_live(parts[2])
            if result.get("status") in ("ok", "warning"):
                return (
                    f"Live apply {result.get('status')}\n"
                    f"Backup: {result.get('backup_path')}\n"
                    f"File: {result.get('applied_path')}\n"
                    f"Compile: {result.get('compile_msg')}"
                )
            return f"Live apply blocked/failed: {result.get('error', result)}"

        return (
            "Healing commands:\n"
            "/heal — recent proposals\n"
            "/heal show <id>\n"
            "/heal apply <id> — worktree preview\n"
            "/heal live <id> — needs PROM_HEALING_LIVE_APPLY=1"
        )

    def _route_folder_context(self, text: str) -> str:
        try:
            return resolve_context_reply(text)
        except Exception as exc:
            return f"Folder context error: {exc}"

    def _route_sentinel(self, text: str) -> GatewayResult:
        from core.orchestrator import orchestrator
        from ghost_sentinel.telegram_cmds import run_sentinel_command

        agent = orchestrator.get_agent("ghost_sentinel")
        if agent is None:
            return GatewayResult(handled=True, reply="Ghost Sentinel agent is not registered.", intent="sentinel")

        def _exec(payload: Dict[str, Any]) -> Dict[str, Any]:
            return agent.execute(payload)

        handled, reply = run_sentinel_command(text, _exec)
        if handled:
            return GatewayResult(handled=True, reply=reply[:MAX_REPLY_LEN], intent="sentinel", agent="ghost_sentinel")
        return GatewayResult(handled=True, reply=None, intent="sentinel", agent="ghost_sentinel")

    def _rag_snippet(self, text: str) -> str:
        try:
            from rag.retriever import retrieve as rag_retrieve
        except Exception:
            return ""
        try:
            rag = rag_retrieve(text, top_k=3)
            return "\n".join(
                f"- {hit['path']} (score={hit['score']}):\n  {hit['snippet']}"
                for hit in rag.get("hits", [])[:3]
            )
        except Exception:
            return ""


def maybe_index_rag() -> None:
    """Optional boot-time RAG index (PROM_RAG_INDEX=1)."""
    if os.getenv("PROM_RAG_INDEX", "").lower() not in ("1", "true", "yes"):
        return
    try:
        from rag.retriever import index_project
        stats = index_project()
        logger.info("rag index built: %s", stats)
    except Exception as exc:
        logger.warning("rag index skipped: %s", exc)


gateway = MessageGateway()