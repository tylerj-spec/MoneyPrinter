"""Immutable experiment specifications and conservative manual-review screens."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import date
from common.validation import digest, number, whole

FEATURES = frozenset({"momentum_20d", "momentum_60d", "trend_50d", "low_volatility", "reversion",
                      "delta", "dte", "iv_solved", "relative_spread", "round_trip_cost_pct_premium",
                      "theta_pct_premium_per_day"})


@dataclass(frozen=True)
class Experiment:
    name: str
    hypothesis: str
    signal_version: str
    features: tuple[str, ...]
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    holdout_start: str
    holdout_end: str
    parameters: tuple[tuple[str, str], ...] = ()

    def validate(self):
        dates = [date.fromisoformat(v) for v in (self.train_start, self.train_end,
                 self.validation_start, self.validation_end, self.holdout_start, self.holdout_end)]
        if not dates[0] <= dates[1] < dates[2] <= dates[3] < dates[4] <= dates[5]:
            raise ValueError("chronological non-overlapping train/validation/holdout required")
        if not self.name or not self.hypothesis or not self.signal_version:
            raise ValueError("name, hypothesis and signal version required")
        if not self.features or len(set(self.features)) != len(self.features) or set(self.features) - FEATURES:
            raise ValueError("unique preregistered decision-feature names required; no outcome features")
        if self.parameters:
            raise ValueError("this model version has fixed hyperparameters; register a new implementation to change them")
        return self

    def record(self):
        self.validate()
        value = asdict(self)
        return {**value, "experiment_id": digest(value), "model_version": "regularized-logistic-1"}


def promotion_decision(*, baseline: dict, challenger: dict, minimum_observations: int = 50):
    """Eligibility for HUMAN review, not automatic weight changes or significance."""
    reasons = []
    try:
        minimum_observations = whole(minimum_observations, "minimum", minimum=1)
        n = whole(challenger.get("observations"), "observations")
        if n < minimum_observations:
            reasons.append("insufficient_fresh_holdout_dates")
        for value in (baseline, challenger):
            number(value.get("net_expectancy"), "net_expectancy")
            drawdown = number(value.get("max_drawdown"), "max_drawdown")
            if drawdown > 0:
                raise ValueError("drawdown must be zero or negative")
        if challenger["net_expectancy"] <= baseline["net_expectancy"]:
            reasons.append("expectancy_not_improved")
        if challenger["max_drawdown"] < baseline["max_drawdown"]:
            reasons.append("drawdown_worse")
        if challenger.get("fresh_forward_holdout") is not True:
            reasons.append("fresh_forward_holdout_not_verified")
        if challenger.get("cohort_sha256") != baseline.get("cohort_sha256") or not baseline.get("cohort_sha256"):
            reasons.append("different_or_unknown_cohort")
        if number(challenger.get("bootstrap_lower_improvement"), "bootstrap lower") <= 0:
            reasons.append("uncertainty_interval_includes_no_improvement")
    except (ValueError, TypeError, KeyError, OverflowError):
        reasons.append("invalid_or_missing_metrics")
    return not reasons, reasons
