"""
Named weight sets over the score components.

The point of running several at once is that NONE of them is known to work.
Committing to a single hand-chosen weighting and paper-trading only that would
produce one unfalsifiable track record. Running a spread of deliberately
different tilts - and logging all of them from the same snapshot - lets the
forward record eventually say which components, if any, carried information.

That is the cheap version of the component rank-IC study the roadmap calls
Phase 4. It does not replace it.

A WARNING ABOUT WHAT MULTIPLE VARIANTS COST. Running five variants and later
reporting the best one is how a coin-flip becomes a strategy. Every variant
here is logged on every run, whether it looks good or not, and the resolver
scores all of them together. The moment a variant is quietly dropped because it
underperformed, the whole record becomes a selection artefact and the count of
independent trials in any significance test is wrong.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Variant:
    name: str
    description: str
    weights: dict[str, float]
    # A directional score must clear this before a contract is proposed at all.
    # Higher means fewer, more concentrated proposals.
    conviction_floor: float = 0.20
    # Which contract to reach for, by absolute delta. 0.35 is a common
    # risk/reward compromise for a directional long: enough sensitivity to be
    # worth the premium, far enough out to cost less than an at-the-money.
    target_abs_delta: float = 0.35

    def normalised_weights(self) -> dict[str, float]:
        total = sum(abs(w) for w in self.weights.values())
        return {k: v / total for k, v in self.weights.items()} if total else dict(self.weights)


VARIANTS: tuple[Variant, ...] = (
    Variant(
        name="momentum",
        description="Trend continuation. Buys strength on the assumption it persists.",
        weights={"momentum_20d": 0.45, "momentum_60d": 0.35, "trend_50d": 0.20},
    ),
    Variant(
        name="trend_quality",
        description="Trend, but penalised for volatility - prefers a smooth advance "
                    "to a violent one, because premium paid scales with volatility.",
        weights={"trend_50d": 0.40, "momentum_60d": 0.30, "low_volatility": 0.30},
    ),
    Variant(
        name="reversion",
        description="The opposite bet. Buys drawdowns on the assumption they revert. "
                    "Included precisely because it contradicts the momentum variants: "
                    "if both look good in the forward record, the record is noise.",
        weights={"reversion": 0.60, "low_volatility": 0.20, "momentum_20d": -0.20},
    ),
    Variant(
        name="balanced",
        description="Even-handed blend of trend, reversion and volatility.",
        weights={"momentum_20d": 0.25, "trend_50d": 0.25, "reversion": 0.25,
                 "low_volatility": 0.25},
    ),
    Variant(
        name="equal_weight_control",
        description="Every component weighted identically. A deliberately naive "
                    "control: any tuned variant that cannot beat this over the "
                    "forward record was not worth tuning.",
        weights={"momentum_20d": 0.20, "momentum_60d": 0.20, "trend_50d": 0.20,
                 "low_volatility": 0.20, "reversion": 0.20},
    ),
)

BY_NAME = {v.name: v for v in VARIANTS}


def score(variant: Variant, scaled: dict[str, float | None]) -> tuple[float | None, list[str]]:
    """Weighted composite in roughly [-1, 1], or None if inputs are missing.

    Fails closed on ANY missing component the variant asks for. Re-normalising
    over whatever happens to be present would silently change the strategy
    being tested from run to run.
    """
    missing = [k for k in variant.weights if scaled.get(k) is None]
    if missing:
        return None, missing
    w = variant.normalised_weights()
    return sum(w[k] * scaled[k] for k in variant.weights), []
