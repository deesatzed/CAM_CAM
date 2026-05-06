"""6-dimensional fitness scoring for methodology memories.

Adapted from xplurx's arena/scoring.py pattern: composite scoring with
weighted dimensions. Each methodology's fitness determines its competitive
standing in the memory ecosystem -- high-fitness memories survive and
reproduce, low-fitness memories decline and die.

Dimensions:
    1. Retrieval Relevance (0.20) -- how relevant this memory is at retrieval time
    2. Outcome Efficacy (0.30) -- EMA-blended success ratio (most important)
    3. Specificity (0.15) -- richness of tags + files metadata
    4. Freshness (0.15) -- exponential decay from creation time
    5. Cross-Domain Transfer (0.10) -- global scope with proven success
    6. Retrieval Frequency (0.10) -- how often this memory is used

Outcome Efficacy uses an Exponential Moving Average (EMA) blended with
the static success ratio. The EMA gives more weight to recent outcomes,
so a methodology that was failing but recently started succeeding sees
its efficacy rise faster than the static ratio alone.  The EMA value
persists in the fitness_vector as ``outcome_ema`` between calls.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from claw.core.models import Methodology

if TYPE_CHECKING:
    from claw.db.engine import DatabaseEngine

logger = logging.getLogger("claw.memory.fitness")

# Dimension weights (sum = 1.0)
W_RELEVANCE = 0.20
W_EFFICACY = 0.30
W_SPECIFICITY = 0.15
W_FRESHNESS = 0.15
W_CROSS_DOMAIN = 0.10
W_FREQUENCY = 0.10

# Freshness half-life in days (legacy constant, still used as fallback)
FRESHNESS_HALF_LIFE_DAYS = 90.0

# Temporal decay tiers — replace single half-life with context-sensitive tiers
DECAY_TIERS: dict[str, float] = {
    "core": float("inf"),   # Seed/architecture: never decays
    "active": 30.0,         # Recently retrieved + used: fast decay encourages freshness
    "warm": 90.0,           # Within 90 days: matches legacy behavior
    "cold": 180.0,          # 90-180 days: slower decay
    "archive": 365.0,       # 180+ days: very slow decay (preservation)
}

# EMA smoothing factor for outcome efficacy.
# Alpha=0.3 means 30% weight on the latest outcome, 70% on the running average.
# Higher alpha = faster adaptation to recent performance changes.
EMA_ALPHA = 0.3

# Blend weights: how much of efficacy comes from EMA vs static ratio.
# Once an EMA is established, efficacy = 60% EMA + 40% static ratio.
# This prevents a single lucky/unlucky outcome from dominating.
EMA_BLEND_WEIGHT = 0.6
STATIC_BLEND_WEIGHT = 1.0 - EMA_BLEND_WEIGHT

# Default category weights — architecture and security get a boost,
# debugging-focused categories are neutral.  All unrecognized categories
# default to 1.0 (no change).  These can be overridden in claw.toml
# via [memory] category_weights = {architecture = 1.5, ...}
DEFAULT_CATEGORY_WEIGHTS: dict[str, float] = {
    "architecture": 1.4,
    "security": 1.3,
    "testing": 1.2,
    "ai_integration": 1.1,
    "data_processing": 1.1,
    "code_quality": 1.0,
    "cli_ux": 1.0,
    "cross_cutting": 1.0,
    "debugging": 1.0,
    "error_handling": 1.0,
}


def _extract_category(tags: list[str]) -> str | None:
    """Extract the first category:* tag value, or None."""
    for t in tags:
        if isinstance(t, str) and t.startswith("category:"):
            return t.split(":", 1)[1]
    return None


def classify_decay_tier(
    methodology: Methodology,
    now: Optional[datetime] = None,
) -> tuple[str, float]:
    """Classify a methodology into a temporal decay tier.

    Returns (tier_name, half_life_days). The tier determines the freshness
    half-life used in fitness scoring.

    Tier logic:
        core    — origin:seed or category:architecture → infinite half-life
        active  — retrieved within 30 days AND ≥3 retrievals → 30-day half-life
        warm    — retrieved within 90 days → 90-day half-life (legacy default)
        cold    — retrieved within 180 days → 180-day half-life
        archive — 180+ days without retrieval → 365-day half-life
    """
    if now is None:
        now = datetime.now(UTC)

    tags = methodology.tags or []

    # Core tier: seed or architecture methodologies never decay
    if "origin:seed" in tags or "category:architecture" in tags:
        return "core", DECAY_TIERS["core"]

    # Determine days since last retrieval (or since creation if never retrieved)
    if methodology.last_retrieved_at:
        if isinstance(methodology.last_retrieved_at, str):
            try:
                last_ret = datetime.fromisoformat(methodology.last_retrieved_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                last_ret = methodology.created_at
        else:
            last_ret = methodology.last_retrieved_at
        days_since = max(0.0, (now - last_ret).total_seconds() / 86400.0)
    else:
        days_since = (now - methodology.created_at).total_seconds() / 86400.0

    # Active tier: recently retrieved AND frequently used
    if days_since <= 30 and methodology.retrieval_count >= 3:
        return "active", DECAY_TIERS["active"]

    # Warm tier: within 90 days (matches legacy 90-day half-life)
    if days_since <= 90:
        return "warm", DECAY_TIERS["warm"]

    # Cold tier: 90-180 days
    if days_since <= 180:
        return "cold", DECAY_TIERS["cold"]

    # Archive tier: 180+ days
    return "archive", DECAY_TIERS["archive"]


def compute_fitness(
    methodology: Methodology,
    retrieval_relevance: float = 0.5,
    max_retrieval_count: int = 1,
    now: Optional[datetime] = None,
    latest_outcome: Optional[bool] = None,
    kelly_posterior_std: Optional[float] = None,
    category_weights: Optional[dict[str, float]] = None,
) -> tuple[float, dict[str, float]]:
    """Compute the 6-dimensional fitness score for a methodology.

    Args:
        methodology: The methodology to score.
        retrieval_relevance: The combined_score from the most recent retrieval
            (hybrid search). Defaults to 0.5 (neutral) when not available.
        max_retrieval_count: The maximum retrieval_count across all active
            methodologies in the same scope. Used to normalize frequency.
        now: Current time for freshness calculation. Defaults to utcnow.
        latest_outcome: The most recent outcome (True=success, False=failure).
            When provided, updates the EMA.  When None (e.g. during bulk
            recomputation), the stored EMA is preserved as-is.
        kelly_posterior_std: Optional posterior std from Bayesian Kelly sizer.
            When provided, applies an uncertainty discount to efficacy:
            agents with high posterior variance (unreliable) reduce the
            efficacy credit of their methodologies.  Capped at 30%.

    Returns:
        Tuple of (total_fitness_score, fitness_vector_dict).
        total_fitness_score is a float in [0.0, 1.0].
        fitness_vector_dict maps dimension names to individual scores.
    """
    if now is None:
        now = datetime.now(UTC)

    # 1. Retrieval Relevance -- from the search engine
    d_relevance = max(0.0, min(1.0, retrieval_relevance))

    # 2. Outcome Efficacy -- EMA-blended success ratio
    #
    # Static ratio: lifetime success_count / total_outcomes (all outcomes equal)
    # EMA: exponential moving average giving 30% weight to latest outcome
    # Final efficacy: 60% EMA + 40% static ratio (when EMA available)
    total_outcomes = methodology.success_count + methodology.failure_count
    if total_outcomes > 0:
        static_efficacy = methodology.success_count / total_outcomes
    else:
        static_efficacy = 0.5  # Unknown: assume neutral

    # Read stored EMA from previous fitness vector (if any)
    prev_ema: Optional[float] = None
    fv = methodology.fitness_vector
    if fv and "outcome_ema" in fv:
        try:
            prev_ema = float(fv["outcome_ema"])
        except (TypeError, ValueError):
            pass

    # Update EMA with latest outcome
    if latest_outcome is not None:
        outcome_val = 1.0 if latest_outcome else 0.0
        if prev_ema is not None:
            outcome_ema = EMA_ALPHA * outcome_val + (1.0 - EMA_ALPHA) * prev_ema
        else:
            # Bootstrap: first outcome seeds the EMA from static ratio
            # blended with the new outcome to avoid a cold-start jump
            outcome_ema = EMA_ALPHA * outcome_val + (1.0 - EMA_ALPHA) * static_efficacy
    else:
        outcome_ema = prev_ema  # preserve stored value (may be None)

    # Blend EMA with static ratio for final efficacy
    if outcome_ema is not None:
        d_efficacy = EMA_BLEND_WEIGHT * outcome_ema + STATIC_BLEND_WEIGHT * static_efficacy
    else:
        d_efficacy = static_efficacy  # no EMA yet, pure static

    # Kelly uncertainty discount: high posterior_std reduces efficacy credit
    if kelly_posterior_std is not None and kelly_posterior_std > 0:
        discount = min(kelly_posterior_std, 0.30)  # cap at 30%
        d_efficacy = d_efficacy * (1.0 - discount)

    # 3. Specificity -- metadata richness
    tag_score = min(1.0, len(methodology.tags) / 5.0)
    files_score = min(1.0, len(methodology.files_affected) / 10.0)
    d_specificity = (tag_score + files_score) / 2.0

    # 4. Freshness -- exponential decay with tier-specific half-life
    decay_tier, tier_half_life = classify_decay_tier(methodology, now=now)
    age_days = (now - methodology.created_at).total_seconds() / 86400.0
    if math.isinf(tier_half_life):
        d_freshness = 1.0  # Core tier: never decays
    else:
        d_freshness = math.exp(-0.693 * age_days / tier_half_life)

    # 5. Cross-Domain Transfer -- global + successful
    if methodology.scope == "global" and methodology.success_count > 0:
        d_cross_domain = 1.0
    elif methodology.scope == "global":
        d_cross_domain = 0.3  # Global but unproven
    else:
        d_cross_domain = 0.0

    # 6. Retrieval Frequency -- normalized
    safe_max = max(1, max_retrieval_count)
    d_frequency = min(1.0, methodology.retrieval_count / safe_max)

    # Weighted sum
    total = (
        W_RELEVANCE * d_relevance
        + W_EFFICACY * d_efficacy
        + W_SPECIFICITY * d_specificity
        + W_FRESHNESS * d_freshness
        + W_CROSS_DOMAIN * d_cross_domain
        + W_FREQUENCY * d_frequency
    )

    # Category weight multiplier — boosts/dampens total based on category tag
    category = _extract_category(methodology.tags or [])
    weights = category_weights if category_weights is not None else DEFAULT_CATEGORY_WEIGHTS
    category_weight = weights.get(category, 1.0) if category else 1.0
    total = min(1.0, total * category_weight)

    vector = {
        "retrieval_relevance": round(d_relevance, 4),
        "outcome_efficacy": round(d_efficacy, 4),
        "specificity": round(d_specificity, 4),
        "freshness": round(d_freshness, 4),
        "cross_domain_transfer": round(d_cross_domain, 4),
        "retrieval_frequency": round(d_frequency, 4),
        "total": round(total, 4),
    }

    # Persist decay tier for observability
    vector["decay_tier"] = decay_tier

    # Persist category weight for observability
    if category_weight != 1.0:
        vector["category_weight"] = round(category_weight, 4)

    # Persist EMA state for next computation
    if outcome_ema is not None:
        vector["outcome_ema"] = round(outcome_ema, 4)

    # Persist Kelly uncertainty for observability
    if kelly_posterior_std is not None:
        vector["kelly_posterior_std"] = round(kelly_posterior_std, 4)

    return round(total, 4), vector


def get_fitness_score(methodology: Methodology) -> float:
    """Extract the stored total fitness score, with neutral fallback.

    Used by retrieval to read cached fitness without recomputation.
    """
    fv = methodology.fitness_vector
    if fv and "total" in fv:
        try:
            return float(fv["total"])
        except (TypeError, ValueError):
            pass
    return 0.5  # Neutral fallback for legacy/unscored entries


async def log_fitness_change(
    engine: "DatabaseEngine",
    methodology_id: str,
    fitness_total: float,
    fitness_vector: dict[str, float],
    trigger_event: str = "recompute",
) -> None:
    """Persist a fitness computation to the history log.

    Args:
        engine: The DatabaseEngine instance for DB access.
        methodology_id: Which methodology was scored.
        fitness_total: The computed total fitness score.
        fitness_vector: Full dimension breakdown dict.
        trigger_event: What caused this recomputation (e.g. 'recompute',
            'outcome_success', 'outcome_failure', 'lifecycle_transition').
    """
    import json
    import uuid

    try:
        await engine.execute(
            "INSERT INTO methodology_fitness_log (id, methodology_id, fitness_total, fitness_vector, trigger_event) VALUES (?, ?, ?, ?, ?)",
            [str(uuid.uuid4()), methodology_id, fitness_total, json.dumps(fitness_vector), trigger_event],
        )
    except Exception as e:
        logger.warning("Failed to log fitness change for %s: %s", methodology_id, e)
