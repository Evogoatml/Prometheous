"""
System-side decision engine.

Takes an intent (parsed from user input by the LLM gateway OR by the intent
parser) and a context, then decides:
  1. Which agent to dispatch to (if any)
  2. Whether to ask the LLM for a response
  3. Whether to write to memory

Rule-based + intent matching. NO LLM call from inside here.
The LLM is purely a translator in/out; the system decides.
"""
import re
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Lazy import: memory.user_prefs touches EncryptedVault which has its own
# dotenv path. We only need it when biasing on user prefs, so a defer
# avoids a hard dependency at engine construction time.
def _user_prefs(chat_id: int) -> Dict[str, Any]:
    try:
        from memory.user_prefs import get_prefs
        return get_prefs(chat_id)
    except Exception:  # noqa: BLE001
        return {}


@dataclass
class Decision:
    action: str               # "dispatch" | "respond" | "create_skill" | "run_skill" | "call_tool"
    agent: Optional[str] = None
    target: Optional[str] = None
    skill_name: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    reason: str = ""
    confidence: float = 0.5


# Keyword → intent map. Order matters: more specific patterns first.
INTENT_PATTERNS: List[Tuple[str, re.Pattern, str, str]] = [
    # (intent_name, regex, default_agent, description)
    ("create_skill", re.compile(r"^create skill\s+(.+)$", re.I), "skill_builder", "create a new skill"),
    ("run_skill",    re.compile(r"^(?:run|execute)\s+skill\s+(.+)$", re.I), "skill_runner", "run a named skill"),
    # Growth — handle the task; never fall through to chat "I can't"
    ("shopify_ads",  re.compile(
        r"(?:^/ads\b|"
        r"\b(?:shopify\s+)?ad\s*campaigns?\b|"
        r"\b(?:meta|facebook|tiktok|instagram)\s+ads?\b|"
        r"\b(?:run|build|create|launch|make|set\s*up|setup)\s+(?:my\s+)?(?:shopify\s+)?(?:ads?|ad\s*campaigns?)\b|"
        r"\bads?\s+for\s+(?:my\s+)?shopify\b|"
        r"\bshopify\s+(?:ads?|marketing|campaigns?)\b)",
        re.I,
    ), "shopify_ads", "shopify / meta ad campaign"),
    # Directed learning — user tells the agent what topic to learn
    ("learn",        re.compile(
        r"(?:^/learn(?:ing)?\b|"
        r"^(?:learn|study)\s+(?:about\s+)?(?!from\s+(?:github|huggingface|hf)\b).+|"
        r"\bi\s+want\s+you\s+to\s+learn\b|"
        r"\bplease\s+learn\b|"
        r"\bteach\s+yourself\s+(?!how\b)|"
        r"\byou\s+should\s+learn\b|"
        r"\bremember\s+to\s+learn\b|"
        r"\badd\s+to\s+(?:your\s+)?(?:curriculum|learning\s+queue)\b)",
        re.I,
    ), "learn", "user-directed topic learning"),
    # Self-growth via GitHub + HuggingFace
    ("growth",       re.compile(
        r"(?:^/grow\b|"
        r"\bgrow\b|"
        r"\bself[- ]?(?:grow|improve|evolve)\b|"
        r"\blearn\s+from\s+(?:github|huggingface|hf)\b|"
        r"\bfigure\s+it\s+out\b|"
        r"\bimprove\s+(?:yourself|prometheous|the\s+agent|your\s+skills)\b|"
        r"\bconnect\s+(?:to\s+)?(?:github|huggingface|hf)\b|"
        r"\bfind\s+(?:code|repos?|libraries?|packages?)\b.*\b(?:github|huggingface|hf)\b|"
        r"\b(?:github|huggingface|hf)\b.*\b(?:code|repos?|models?|datasets?)\b)",
        re.I,
    ), "growth", "self-growth github+hf"),
    ("reflect",      re.compile(r"\b(?:/reflect\b|self[- ]?audit|audit yourself|paradox audit|reflect on|paradox)\b", re.I), "paradox", "reflect / paradox audit"),
    ("ghost_sentinel", re.compile(r"\b(?:ghost\s*sentinel|sentinel\s+sync|sentinel\s+poll|mcp\s+tool|crdt\s+sync)\b", re.I), "ghost_sentinel", "ghost sentinel CRDT/MCP"),
    # Mission: plan → code → deploy → execute (+ CrewAI/SuperAGI/AgentGPT/AgentK/Swarms)
    ("mission",      re.compile(
        r"(?:^/mission\b|^/do\b|"
        r"\bmission\b|"
        r"\bplan\s+(?:and\s+)?(?:code|build|implement|deploy)\b|"
        r"\bdeploy\s+(?:a\s+|an\s+)?(?:new\s+)?(?:[\w-]+\s+)*(?:agent|bot|worker)s?\b|"
        r"\bbuild\s+(?:me\s+)?(?:a\s+|an\s+)?(?:[\w-]+\s+)*(?:agent|bot)s?\b|"
        r"\bcreate\s+(?:a\s+|an\s+)?(?:[\w-]+\s+)*(?:agent|bot)s?\b|"
        r"\bwrite\s+code\s+and\s+deploy\b|"
        r"\bplan\s+it\s+out\b|"
        r"\bget\s+it\s+done\b|"
        r"\b(?:crewai|crew\s*ai|superagi|super\s*agi|agentgpt|agent\s*gpt|"
        r"agent\s*k|agentk|swarm\s*ai|swarms?)\b)",
        re.I,
    ), "mission", "plan→code→deploy→execute"),
    # Explicit mosaic / polymorphic assembly
    ("mosaic",       re.compile(
        r"(?:^/mosaic\b|"
        r"\b(?:run\s+)?mosaic\b|"
        r"\bpolymorphic\b|"
        r"\bauto[- ]?mosaic\b|"
        r"\bassemble\s+(?:agents|tiles|swarm)\b)",
        re.I,
    ), "mosaic", "polymorphic auto-mosaic"),
    ("web_search",   re.compile(r"(?:^/search\b|^search\s+(?!the web)|\b(?:search\s+the\s+web|look\s+up|google|web\s+search|tell me about (?:llms?|language models?))\b)", re.I), "web_search", "web search"),
    ("identity",     re.compile(r"\b(?:who are you|what are you|what model|which model|what llm|your name|are you (?:gpt|claude|grok|minimax|chatgpt))\b", re.I), None, "identity"),
    # "make yourself better" → actually grow, don't lecture about /commands
    ("improve",      re.compile(
        r"\b(?:how (?:do|can) (?:i|you) (?:make|improve|train|teach)|"
        r"make (?:you|yourself) (?:better|stronger|smarter)|"
        r"how (?:do|can) you learn|can you learn from|"
        r"become more capable|get smarter|improve (?:you|yourself|prometheous)|"
        r"teach yourself|train yourself|level up|"
        r"find (?:code|repos?|libraries) (?:for|on) (?:github|hf|huggingface))\b",
        re.I,
    ), "growth", "self-improve via github+hf"),
    # Exact capability queries only — not "what can you do about X" (that's a task)
    ("abilities",    re.compile(
        r"^(?:what are your abilities|what can you do|what do you do|your capabilities|your abilities)\s*[?.!]*$",
        re.I,
    ), None, "abilities"),
    ("commands",     re.compile(r"(?:^/commands\b|^commands$)\b", re.I), None, "commands"),
    ("scan",         re.compile(r"\b(?:scan|nmap|port\s*scan)\b", re.I), "scanner",  "scan"),
    # Ability / algorithm knowledge
    ("knowledge",    re.compile(
        r"(?:^/knowledge\b|"
        r"\b(?:ability\s+knowledge|algorithm\s+knowledge)\b|"
        r"\b(?:how\s+(?:does|do)\s+(?:aes|rsa|dijkstra|quicksort|bfs|dfs)\b)|"
        r"\b(?:explain|lookup|find)\s+(?:the\s+)?(?:algorithm|cipher|hash|sort|graph)\b)",
        re.I,
    ), "knowledge", "ability knowledge"),
    # Natural language status / agents (no slash required)
    ("status",       re.compile(r"^(?:status|are you (?:online|up|alive)|health check)\s*[?.!]*$", re.I), None, "status"),
    ("agents",       re.compile(r"^(?:(?:list |show )?agents|who(?:'s| is) working)\s*[?.!]*$", re.I), None, "agents"),
    ("greet",        re.compile(
        r"^(?:hi|hello|hey|alive|sup|yo|howdy|hiya|good\s+(?:morning|afternoon|evening)|"
        r"what'?s\s+up|whats\s+up|how are you|how'?s it going)[\s!.?]*$",
        re.I,
    ), None, "greeting"),
    ("chat",         re.compile(r".+", re.I), None, "general chat"),  # catch-all → talk or task
]


class DecisionEngine:
    """Picks an action from a user message. No LLM."""

    def __init__(self):
        self.history: List[Decision] = []
        self.max_history = 100

    def decide(self, message: str, context: Optional[Dict[str, Any]] = None) -> Decision:
        ctx = context or {}
        text = message.strip()
        lower = text.lower()

        tool_decision = self._try_tool_call(text)
        if tool_decision is not None:
            return tool_decision

        for intent_name, pattern, agent, desc in INTENT_PATTERNS:
            m = pattern.search(text)
            if not m:
                continue

            # Build the decision
            reason = f"matched intent '{intent_name}' ({desc})"
            confidence = 0.9 if intent_name in (
                "scan", "create_skill", "run_skill", "web_search", "shopify_ads", "growth", "learn"
            ) else 0.7

            if intent_name == "learn":
                return self._record(Decision(
                    action="dispatch",
                    agent="learn",
                    target=text,
                    reason=reason,
                    confidence=0.96,
                ))

            if intent_name == "knowledge":
                return self._record(Decision(
                    action="dispatch",
                    agent="knowledge",
                    target=text,
                    reason=reason,
                    confidence=0.92,
                ))

            if intent_name == "mission":
                return self._record(Decision(
                    action="dispatch",
                    agent="mission",
                    target=text,
                    reason=reason,
                    confidence=0.96,
                ))

            if intent_name == "mosaic":
                return self._record(Decision(
                    action="dispatch",
                    agent="mosaic",
                    target=text,
                    reason=reason,
                    confidence=0.95,
                ))

            if intent_name == "shopify_ads":
                return self._record(Decision(
                    action="dispatch",
                    agent="shopify_ads",
                    target=text,
                    reason=reason,
                    confidence=0.95,
                ))

            if intent_name in ("growth", "improve"):
                return self._record(Decision(
                    action="dispatch",
                    agent="growth",
                    target=text,
                    reason=reason,
                    confidence=0.95,
                ))

            if intent_name == "web_search":
                query = text
                for strip_pat in (
                    r"^/search\s+",
                    r"^tell me about\s+",
                    r"^(?:search\s+the\s+web\s+for|look\s+up|google|web\s+search)\s+",
                    r"^search\s+",
                ):
                    query = re.sub(strip_pat, "", query, flags=re.I).strip()
                return self._record(Decision(
                    action="dispatch",
                    agent=agent,
                    target=query.strip("?").strip(),
                    reason=reason,
                    confidence=confidence,
                ))

            if intent_name == "create_skill":
                skill = m.group(1).strip().replace(" ", "_")
                return self._record(Decision(
                    action="create_skill",
                    skill_name=skill,
                    reason=reason,
                    confidence=confidence,
                ))

            if intent_name == "run_skill":
                skill = m.group(1).strip().replace(" ", "_")
                return self._record(Decision(
                    action="run_skill",
                    skill_name=skill,
                    reason=reason,
                    confidence=confidence,
                ))

            if intent_name == "identity":
                return self._record(Decision(
                    action="respond",
                    reason=reason,
                    confidence=0.95,
                ))

            if intent_name == "improve":
                return self._record(Decision(
                    action="respond",
                    reason=reason,
                    confidence=0.95,
                ))

            if intent_name == "abilities":
                return self._record(Decision(
                    action="respond",
                    reason=reason,
                    confidence=0.95,
                ))

            if intent_name == "commands":
                return self._record(Decision(
                    action="respond",
                    reason=reason,
                    confidence=0.95,
                ))

            if intent_name == "status":
                return self._record(Decision(
                    action="respond",
                    reason="status",
                    confidence=0.95,
                ))

            if intent_name == "agents":
                return self._record(Decision(
                    action="respond",
                    reason="agents",
                    confidence=0.95,
                ))

            if intent_name == "greet":
                return self._record(Decision(
                    action="respond",
                    reason="greet",
                    confidence=0.9,
                ))

            if intent_name == "chat":
                # Conversation vs work: talk like a person unless they clearly
                # want something done (write/build/search/run/…).
                from llm.conversation import looks_like_conversation, looks_like_work

                if looks_like_conversation(text) and not looks_like_work(text):
                    return self._record(Decision(
                        action="respond",
                        reason="chat",
                        target=text,
                        confidence=0.88,
                    ))
                # Actionable goal → general task executor (never pure refuse).
                return self._record(Decision(
                    action="dispatch",
                    agent="task",
                    target=text,
                    reason=f"{reason}; work request → task executor",
                    confidence=0.85,
                ))

            # dispatchable intent
            return self._record(Decision(
                action="dispatch",
                agent=agent,
                target=ctx.get("target"),
                reason=reason,
                confidence=confidence,
            ))

        # Final safety: still execute, never pure refuse
        return self._record(Decision(
            action="dispatch",
            agent="task",
            target=text,
            reason="fallback executor",
            confidence=0.5,
        ))

    def _try_tool_call(self, text: str) -> Optional[Decision]:
        """Route MCP function calls through orchestrator (not Telegram-only)."""
        from llm.tool_router import classify_tool

        normalized = text
        if normalized.lower().startswith("/tool "):
            normalized = "tool:" + normalized[6:].strip()

        call = classify_tool(normalized)
        if call is None:
            return None
        # web_search agent handles search; tools path only for explicit tool:web.search
        if call.name == "web.search" and call.source != "explicit":
            return None
        if call.confidence < 0.8 and call.source != "explicit":
            return None

        return self._record(Decision(
            action="call_tool",
            agent="mcp_tools",
            tool_name=call.name,
            tool_args=call.arguments,
            reason=f"tool router ({call.source}) → {call.name}",
            confidence=call.confidence,
        ))

    def _record(self, d: Decision) -> Decision:
        self.history.append(d)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]
        logger.info("decision: %s (conf=%.2f) — %s", d.action, d.confidence, d.reason)
        return d


# Single shared instance
engine = DecisionEngine()
