"""Shared recall ranking: lexical × recency × success (tunable weights)."""

from __future__ import annotations

import re
import time
from typing import Set


def tokens(text: str) -> Set[str]:
    return set(re.findall(r"[a-z0-9_]{2,}", (text or "").lower()))


def rank_score(
    *,
    content: str,
    query_tokens: Set[str],
    tags: list | None = None,
    query_tags: list | None = None,
    created_at: float = 0.0,
    provenance: dict | None = None,
) -> float:
    """
    Higher is better. Weights come from active TuningParams when available.
    """
    try:
        from ..learning.tuning_state import get_active_tuning

        p = get_active_tuning()
        w_lex = p.w_lexical
        w_tag = p.w_tag
        w_cov = p.w_coverage
        w_rec = p.w_recency
        w_suc = p.w_success
        w_fail = p.w_fail_penalty
        half_life_days = p.half_life_days
    except Exception:
        w_lex = 1.0
        w_tag = 1.5
        w_cov = 1.5
        w_rec = 2.0
        w_suc = 1.25
        w_fail = 0.5
        half_life_days = 3.0

    tags = tags or []
    query_tags = query_tags or []
    provenance = provenance or {}
    text = (content or "").lower()

    score = 0.0
    for t in query_tokens:
        if t in text:
            score += w_lex
        elif any(t in w for w in text.split() if len(w) > 3):
            score += 0.35 * w_lex

    for tag in query_tags:
        if tag in tags:
            score += w_tag

    if len(query_tokens) >= 2:
        coverage = sum(1 for t in query_tokens if t in text) / max(len(query_tokens), 1)
        score += coverage * w_cov

    now = time.time()
    age = max(now - (created_at or now), 1.0)
    half_life = max(half_life_days, 0.1) * 86400.0
    recency = 0.5 ** (age / half_life)
    score += recency * w_rec

    success = provenance.get("success")
    if success is True:
        score += w_suc
    elif success is False:
        score -= w_fail

    if provenance.get("kind") == "noise" or "noise" in tags:
        score -= 2.0

    return score
