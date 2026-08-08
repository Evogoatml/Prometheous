"""
DecisionController — bridges the rest of the system to the canonical
Prometheous DecisionEngine.  The engine is rule-based; the LLM never decides.
"""
from core.decision import DecisionEngine

engine = DecisionEngine()


class DecisionController:
    def __init__(self) -> None:
        self.engine = engine

    def execute(self, context):
        return self.engine.decide(context.get("user_msg", ""), context=context)
