"""
Canonical Prometheous Telegram commands — single source of truth.

The LLM must NOT invent commands outside this list.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# (command, description)
TELEGRAM_COMMANDS: List[tuple[str, str]] = [
    ("/start", "Welcome + capability overview"),
    ("/help", "Same as /start"),
    ("/commands", "This command list (accurate, no hallucinations)"),
    ("/abilities", "Short capability summary (use /commands for full list)"),
    ("/status", "Gateway + agent count"),
    ("/agents", "List registered specialist agents"),
    ("/search <query>", "Web search (DuckDuckGo / SerpAPI)"),
    ("/ads", "Build Shopify/Meta ad campaign (autonomous — no Q&A)"),
    ("/ads launch", "Same + push PAUSED structure to Meta (needs keys + ADS_AUTONOMOUS_LAUNCH=1)"),
    ("/learn <topic>", "Tell me what to learn — research + save notes to curriculum"),
    ("/learn list", "Show learning curriculum (pending + learned)"),
    ("/learn next", "Learn the next queued topic"),
    ("/learn queue <topic>", "Queue a topic without researching yet"),
    ("/grow <skill>", "Self-growth: GitHub + HuggingFace research → new skill package"),
    ("/reflect", "Paradox self-audit (system facts, not LLM testimony)"),
    ("/audit", "Alias for /reflect"),
    ("/sentinel", "Ghost Sentinel status"),
    ("/sentinel help", "Ghost Sentinel commands"),
    ("/sentinel sync", "Publish CRDT delta to relay"),
    ("/sentinel poll", "Ingest peer relay messages"),
    ("/sentinel tools", "List gated tool templates"),
    ("/sentinel tool <tpl> <name>", "Register a template tool"),
    ("/context <folder>", "On-demand folder file index (e.g. /context ghost_sentinel)"),
    ("/heal", "Recent self-healing proposals"),
    ("/heal show <id>", "Show one proposal"),
    ("/heal apply <id>", "Apply patch to worktree (safe preview)"),
    ("/heal live <id>", "Apply to live file (requires PROM_HEALING_LIVE_APPLY=1)"),
    ("/tool <name> key=value", "MCP function call via orchestrator"),
]

NATURAL_LANGUAGE_HINTS = [
    "any goal in plain language — task agent attempts it (no 'I can't')",
    "learn python asyncio — directed learning (research + notes)",
    "I want you to learn graph rag — same, no slash needed",
    "grow agent memory from github — self-growth (GitHub + HuggingFace)",
    "search github for langgraph agents — github.search tool",
    "search huggingface for instruction tuning — hf.search_models",
    "scan <target> — scanner",
    "search the web for … — web search",
    "build me a shopify ad campaign — ads agent",
    "fetch https://… — http.get",
    "read file main.py — fs.read",
    "self-audit — paradox",
    "who are you — identity",
]

# Shown in /abilities and /agents — not the full integration roster
CORE_AGENTS = (
    "task",
    "learn",
    "growth",
    "scanner",
    "paradox",
    "ghost_sentinel",
    "web_search",
    "shopify_ads",
    "mcp_tools",
    "knowledge",
    "skill_builder",
    "skill_runner",
)


def format_welcome_text() -> str:
    """Short /start and /help — plain language first; slashes optional."""
    return "\n".join([
        "Hey — I'm Prometheous.",
        "",
        "Talk to me like a person. No slash commands required.",
        "",
        "You can throw stuff at me like:",
        "• \"build a shopify ad campaign\"",
        "• \"find agent memory code on github\"",
        "• \"learn python asyncio\"",
        "• \"research pricing for digital products\"",
        "• \"read file requirements.txt\"",
        "• or just chat — ideas, questions, whatever's on your mind",
        "",
        "I actually do the work (agents, search, files, tools) — I don't hide behind 'I can't'.",
        "What are you working on?",
    ])


def is_improve_request(text: str) -> bool:
    """Meta questions about self-improvement — not directed 'learn <topic>'."""
    t = (text or "").lower().strip()
    # Directed learning has its own path (LearnAgent / decision "learn")
    if re.match(
        r"^(?:/learn|learn|study)\s+\S+",
        t,
    ) or re.search(
        r"\b(?:i want you to learn|please learn|you should learn|remember to learn)\b",
        t,
    ):
        return False
    patterns = (
        "how do i make you",
        "how can i make you",
        "how to make you",
        "make you better",
        "make you stronger",
        "how do you learn",
        "how can you learn",
        "can you learn",
        "teach you",
        "train you",
        "improve you",
        "get smarter",
        "become more capable",
        "how do i improve",
    )
    return any(p in t for p in patterns)


def format_improve_text() -> str:
    """Fallback only — prefer routing to growth agent."""
    return "\n".join([
        "🟠 Self-growth",
        "",
        "Say it in plain language, for example:",
        "• learn python asyncio",
        "• I want you to learn graph rag",
        "• make yourself better at agent memory",
        "• learn recursive memory from github",
        "• grow shopify ads skills",
        "",
        "/learn <topic> researches and saves notes.",
        "/grow packages a skill from GitHub + HuggingFace.",
    ])


def format_abilities_text(agent_names: List[str] | None = None) -> str:
    """Compact /abilities — no agent wall."""
    names = [n for n in (agent_names or []) if n != "telegram"]
    core = [a for a in CORE_AGENTS if a in names]
    extra = len(names) - len(core)

    lines = [
        "I'm Prometheous — talk to me normally.",
        "",
        "I can research, write, run tools, learn topics, grow skills, "
        "build ad campaigns, search the web, and more.",
        "I don't refuse with empty 'I can't' — I try.",
        "",
    ]
    if core:
        lines.append("Specialists: " + ", ".join(core))
    if extra > 0:
        lines.append(f"Also loaded: {extra} integration agent(s) — /agents")
    lines.extend(["", "/commands — full list"])
    return "\n".join(lines)


def format_agents_text(agent_names: List[str]) -> str:
    """Grouped /agents — core first, integrations collapsed."""
    names = sorted(n for n in agent_names if n != "telegram")
    if not names:
        return "🟠 No agents registered yet."

    core = [a for a in CORE_AGENTS if a in names]
    other = [a for a in names if a not in CORE_AGENTS]

    lines = ["🟠 Agents", ""]
    if core:
        lines.append("Core:")
        lines.extend(f"  {a}" for a in core)
    if other:
        lines.append("")
        lines.append(f"Integrations ({len(other)}):")
        show = other[:8]
        lines.extend(f"  {a}" for a in show)
        if len(other) > 8:
            lines.append(f"  …+{len(other) - 8} more")
    return "\n".join(lines)


def normalize_telegram_command(text: str) -> Tuple[str, str]:
    """
    Normalize Telegram slash commands.

    Strips @botname suffixes and lowercases the command head while preserving args.
    Returns (command_head, original_text).
    """
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return raw.lower(), raw

    parts = raw.split(maxsplit=1)
    head = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    if "@" in head:
        head = head.split("@", 1)[0]
    head = head.lower()
    if args:
        return head, f"{head} {args}"
    return head, head


def command_head(text: str) -> str:
    """First slash token, without @botname (e.g. /search@bot -> /search)."""
    return normalize_telegram_command(text)[0]


def is_commands_request(text: str) -> bool:
    head = command_head(text)
    return head in {"/commands", "/command"}


def is_context_request(text: str) -> bool:
    """True for /context with or without a folder argument."""
    return command_head(text) == "/context"


def format_context_usage() -> str:
    return (
        "Usage: /context <folder>\n\n"
        "Examples:\n"
        "• /context ghost_sentinel\n"
        "• /context agents\n"
        "• /context core/orchestrator\n\n"
        "Lists tracked files in that folder (cached on demand)."
    )


def resolve_context_reply(text: str) -> str:
    """
    Deterministic /context handler — never LLM.

    Returns reply text. Raises on unexpected errors (caller may catch).
    """
    if not is_context_request(text):
        raise ValueError("not a /context request")

    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return format_context_usage()

    from knowledge.folder_index import format_folder_summary, scan_folder

    folder = parts[1].strip()
    ctx = scan_folder(folder)
    if ctx.get("status") != "ok":
        return ctx.get("error", "Folder scan failed.")
    return format_folder_summary(ctx)


def format_commands_text() -> str:
    groups = [
        ("General", ("/start", "/help", "/commands", "/abilities", "/status", "/agents")),
        ("Work", (
            "/search <query>", "/learn <topic>", "/learn list", "/learn next",
            "/ads", "/ads launch", "/grow <skill>", "/reflect", "/audit", "/context <folder>",
        )),
        ("Ghost Sentinel", (
            "/sentinel", "/sentinel help", "/sentinel sync", "/sentinel poll",
            "/sentinel tools", "/sentinel tool <tpl> <name>",
        )),
        ("Self-healing", ("/heal", "/heal show <id>", "/heal apply <id>", "/heal live <id>")),
        ("Tools", ("/tool <name> key=value",)),
    ]
    desc_map = dict(TELEGRAM_COMMANDS)
    lines = ["🟠 Prometheous — commands", ""]
    for title, cmds in groups:
        lines.append(title + ":")
        for cmd in cmds:
            desc = desc_map.get(cmd, "")
            lines.append(f"  {cmd}" + (f" — {desc}" if desc else ""))
        lines.append("")
    lines.append("Preferred: plain language (no slash needed):")
    for hint in NATURAL_LANGUAGE_HINTS:
        lines.append(f"  {hint}")
    lines.append("")
    lines.append("Slash commands are optional shortcuts only.")
    return "\n".join(lines)


COMMAND_NAMES = frozenset(
    c.split()[0].lower()
    for c, _ in TELEGRAM_COMMANDS
    if c.startswith("/")
) | {"/commands", "/context"}

PROMPT = "🟠 Prometheous"

ABILITIES_TRIGGERS = (
    "what are your abilities",
    "what are you abilities",
    "what can you do",
    "what do you do",
    "your abilities",
    "your capabilities",
    "what are your capabilities",
    "help me",
    "what can u do",
)

IDENTITY_TRIGGERS = (
    "who are you",
    "what are you",
    "what model are you",
    "which model are you",
    "what llm are you",
    "are you gpt",
    "are you claude",
    "are you grok",
    "are you minimax",
    "are you chatgpt",
    "your name",
)

IDENTITY_REPLY = (
    "I'm Prometheous. Think of me as someone who actually gets things done — "
    "not a single chatbot model (not GPT, Claude, Grok, or MiniMax).\n\n"
    "Talk normally. I'll remember the thread, answer like a person, and when you "
    "want real work done I'll run tools and agents for it. No menu required."
)


def is_identity_request(text: str) -> bool:
    command = command_head(text)
    return any(trigger in command for trigger in IDENTITY_TRIGGERS)


def is_abilities_request(text: str) -> bool:
    """True only for capability questions, not 'what can you do about <task>'."""
    t = (text or "").strip().lower()
    if re.search(r"what can you do about\b", t):
        return False
    # Whole-message capability probes (not embedded in a work request)
    if re.fullmatch(
        r"(?:what are your abilities|what can you do|what do you do|your capabilities|"
        r"your abilities|what can u do|help me)\s*[?.!]?",
        t,
    ):
        return True
    command = command_head(text)
    if command in {"/abilities", "/capabilities"}:
        return True
    return False