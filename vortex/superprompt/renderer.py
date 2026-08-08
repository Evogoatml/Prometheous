"""Render SuperPrompt system messages for agents and training."""
from __future__ import annotations

from typing import Optional

from vortex.superprompt.templates import (
    CTMS_ACTIVATION,
    NEOVERTEX_V1,
    SUPERPROMPT_V2_OMEGA,
    VORTEX_GRAPHRAG_SYSTEM,
)


class SuperPromptRenderer:
    """Compose NeoVertex SuperPrompt variants for runtime and SFT."""

    DEFAULT_META = {
        "Type": "Universal Catalyst",
        "Purpose": "Infinite Conceptual Evolution",
        "Paradigm": "Metamorphic Abstract Reasoning",
        "Constraints": "Self-Transcending",
    }

    def __init__(self, variant: str = "vortex"):
        """
        variant:
          - neovertex_v1 : classic holographic answer_operator
          - omega_v2     : bounded SuperPrompt ΩΣ
          - vortex       : GraphRAG + recursive memory fusion (default)
          - ctms         : CTMS activation only
        """
        self.variant = variant

    def render(
        self,
        task: str = "current task",
        objective: Optional[str] = None,
        memory_state: str = "(empty)",
        graph_context: str = "(none)",
        **meta_overrides,
    ) -> str:
        meta = {**self.DEFAULT_META, **meta_overrides}
        objective = objective or "current-goal"

        if self.variant == "neovertex_v1":
            return NEOVERTEX_V1.format(
                Type=meta["Type"],
                Purpose=meta["Purpose"],
                Paradigm=meta["Paradigm"],
                Constraints=meta["Constraints"],
                objective=objective,
                task=task,
            )

        if self.variant == "omega_v2":
            return (
                SUPERPROMPT_V2_OMEGA
                + f"\n\nObjective: {objective}\nTask: {task}\n"
            )

        if self.variant == "ctms":
            return CTMS_ACTIVATION + f"\nObjective: {objective}\nTask: {task}\n"

        # vortex (default)
        core = SUPERPROMPT_V2_OMEGA + "\n" + CTMS_ACTIVATION
        return VORTEX_GRAPHRAG_SYSTEM.format(
            superprompt_core=core,
            memory_state=memory_state,
            graph_context=graph_context,
        ) + f"\nObjective: {objective}\nTask: {task}\n"

    def with_context(
        self,
        task: str,
        *,
        memory_summary: str = "",
        graph_hits: list | None = None,
        objective: Optional[str] = None,
    ) -> str:
        graph_context = "(none)"
        if graph_hits:
            lines = []
            for i, hit in enumerate(graph_hits[:8], 1):
                if isinstance(hit, (list, tuple)) and len(hit) >= 2:
                    lines.append(f"{i}. [{hit[1]:.3f}] {str(hit[0])[:240]}")
                else:
                    lines.append(f"{i}. {str(hit)[:240]}")
            graph_context = "\n".join(lines)
        return self.render(
            task=task,
            objective=objective,
            memory_state=memory_summary or "(empty)",
            graph_context=graph_context,
        )
