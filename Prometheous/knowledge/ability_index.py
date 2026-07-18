"""
DEPRECATED for bot runtime.

Training corpus → brain index is OFFLINE:
    python -m brain.build_ability_knowledge

Runtime brain queries:
    from brain.knowledge_store import brain_knowledge

knowledge/training/ is NOT part of the bot.
"""
from brain.knowledge_store import brain_knowledge, get_brain_knowledge

# Back-compat aliases (query path only — no training scan)
abilities = brain_knowledge
get_abilities = get_brain_knowledge

__all__ = ["abilities", "get_abilities", "brain_knowledge", "get_brain_knowledge"]
