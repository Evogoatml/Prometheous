"""Consensus utilities for proposal submission, debate, and voting."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Proposal:
    agent: str
    strategy: str
    rationale: str
    confidence: float
    votes: int = 0


class AgentConsensus:
    """Store proposals and select a strategy with simple debate rounds."""

    def __init__(self) -> None:
        self.proposals: Dict[str, Proposal] = {}

    def submit_proposal(self, agent: str, strategy: str, rationale: str, confidence: float) -> Proposal:
        proposal = Proposal(agent=agent, strategy=strategy, rationale=rationale, confidence=float(confidence), votes=0)
        self.proposals[strategy] = proposal
        return proposal

    def vote(self, agent: str, strategy: str, weight: float = 1.0) -> Optional[Proposal]:
        proposal = self.proposals.get(strategy)
        if proposal is None:
            logger.warning("vote ignored for unknown strategy %s by %s", strategy, agent)
            return None
        proposal.votes += max(1, int(round(weight)))
        return proposal

    def negotiate(self, proposals: List[Proposal], rounds: int = 3) -> Proposal:
        active = [proposal for proposal in proposals if proposal]
        if not active:
            raise ValueError("at least one proposal is required")
        for _ in range(max(1, rounds)):
            if len(active) == 1:
                break
            for proposal in active:
                proposal.confidence = min(1.0, proposal.confidence + (float(proposal.votes) * 0.01))
            active.sort(key=lambda item: (item.confidence, float(item.votes)), reverse=True)
            active = active[:-1]
        return self.select_strategy(active)

    def select_strategy(self, proposals: List[Proposal]) -> Proposal:
        if not proposals:
            raise ValueError("at least one proposal is required")
        return max(proposals, key=lambda item: ((float(item.votes) + 1.0) * item.confidence, item.confidence))
