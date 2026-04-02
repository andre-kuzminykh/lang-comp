"""
Bayesian Beta-posterior scoring for AccInt knowledge entries.

Each entry tracks (alpha, beta) — successes and failures.
Thompson sampling ranks entries by both success rate and evidence amount.
Confidence decays over time if entries are not revalidated.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BetaScore:
    """Bayesian Beta posterior for a single knowledge entry."""

    alpha: float = 1.0        # prior successes + 1
    beta: float = 1.0         # prior failures  + 1
    last_used: float = 0.0    # epoch timestamp
    last_updated: float = 0.0 # epoch timestamp
    usage_count: int = 0

    @property
    def mean(self) -> float:
        """Expected success rate: E[θ] = α / (α + β)."""
        return self.alpha / (self.alpha + self.beta)

    @property
    def evidence(self) -> float:
        """Total evidence = α + β - 2 (subtracting the prior)."""
        return self.alpha + self.beta - 2.0

    @property
    def confidence(self) -> float:
        """Confidence ∈ [0, 1] based on evidence amount.

        Uses a sigmoid-like curve: conf = 1 - 1/(1 + evidence/5).
        More evidence → higher confidence.
        """
        return 1.0 - 1.0 / (1.0 + self.evidence / 5.0)

    def record_success(self, weight: float = 1.0) -> None:
        self.alpha += weight
        self.last_updated = time.time()

    def record_failure(self, weight: float = 1.0) -> None:
        self.beta += weight
        self.last_updated = time.time()

    def record_usage(self) -> None:
        self.usage_count += 1
        self.last_used = time.time()

    def to_dict(self) -> dict:
        return {
            "alpha": self.alpha,
            "beta": self.beta,
            "last_used": self.last_used,
            "last_updated": self.last_updated,
            "usage_count": self.usage_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BetaScore":
        return cls(
            alpha=d.get("alpha", 1.0),
            beta=d.get("beta", 1.0),
            last_used=d.get("last_used", 0.0),
            last_updated=d.get("last_updated", 0.0),
            usage_count=d.get("usage_count", 0),
        )


def thompson_sample(score: BetaScore) -> float:
    """Draw a sample from Beta(α, β) for Thompson-sampling-based ranking."""
    return random.betavariate(max(score.alpha, 0.01), max(score.beta, 0.01))


def decay_confidence(
    score: BetaScore,
    now: Optional[float] = None,
    half_life_days: float = 30.0,
) -> BetaScore:
    """Apply time-based confidence decay.

    Shrinks α and β toward the prior (1, 1) based on time since last update.
    Fresh evidence can restore them quickly.
    """
    if now is None:
        now = time.time()
    if score.last_updated <= 0:
        return score

    elapsed_days = (now - score.last_updated) / 86400.0
    if elapsed_days <= 0:
        return score

    # Decay factor: how much of the accumulated evidence survives
    decay = math.pow(0.5, elapsed_days / half_life_days)

    # Shrink toward prior (1, 1)
    score.alpha = 1.0 + (score.alpha - 1.0) * decay
    score.beta = 1.0 + (score.beta - 1.0) * decay
    return score


def rank_entries(entries: List[dict], top_k: int = 10) -> List[dict]:
    """Rank knowledge entries by Thompson sampling.

    Each entry dict must have a "score" key with BetaScore-compatible data.
    Returns top_k entries sorted by sampled score (descending).
    """
    scored = []
    for entry in entries:
        bs = BetaScore.from_dict(entry.get("score", {}))
        sample = thompson_sample(bs)
        scored.append((sample, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]
