"""Versioned, auditable option selection, not a trained profitability model.

The default DELTA policy preserves the existing nearest-delta baseline. The
opt-in COST_AWARE experiment prefers lower execution drag within a delta band,
then delta proximity, theta burden, preferred DTE, spread and displayed volume.
Outside the band it falls back to nearest delta BEFORE cost, rather than picking
an economically different contract solely because it looks cheap. All default
thresholds are research assumptions, not empirically optimized parameters.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
from math import inf, isfinite
from typing import Any, Sequence

from gates.risk import RiskLimits

SELECTION_VERSION = "1.0.0"


@dataclass(frozen=True)
class ContractSelectionPolicy:
    mode: str = "delta"
    delta_tolerance: float = 0.08
    preferred_dte: int = 40

    def __post_init__(self) -> None:
        if self.mode not in ("delta", "cost_aware"):
            raise ValueError("selection mode must be delta or cost_aware")
        tolerance = _num(self.delta_tolerance)
        if tolerance is None or not 0 <= tolerance <= 1:
            raise ValueError("delta_tolerance must be finite and between 0 and 1")
        if type(self.preferred_dte) is not int or self.preferred_dte <= 0:
            raise ValueError("preferred_dte must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {"version": SELECTION_VERSION, **asdict(self),
                "validation_status": "UNVALIDATED_RESEARCH_POLICY"}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


DEFAULT_POLICY = ContractSelectionPolicy()


def eligible(row: Any, kind: str, limits: RiskLimits = RiskLimits()) -> bool:
    """Check each row, not only the first; upstream PASS is not a numeric guard.

    This is quote-shape/liquidity validation, NOT quote-age validation. The
    current feed does not supply a verified quote timestamp for every row.
    """
    if not isinstance(row, dict) or row.get("type") != kind:
        return False
    if row.get("model_status") != "OK" or row.get("liquidity_screen") != "PASS":
        return False
    keys = ("strike", "bid", "ask", "mid", "delta", "dte", "relative_spread",
            "open_interest", "volume", "round_trip_cost_1x", "underlying_close")
    values = {key: _num(row.get(key)) for key in keys}
    if any(value is None for value in values.values()):
        return False
    v = values
    try:
        date.fromisoformat(row["expiration"])
    except (ValueError, TypeError, KeyError):
        return False
    if not (v["strike"] > 0 and v["underlying_close"] > 0 and
            0 < v["bid"] <= v["mid"] <= v["ask"] and v["round_trip_cost_1x"] >= 0):
        return False
    if not (0 < v["delta"] <= 1 if kind == "CALL" else -1 <= v["delta"] < 0):
        return False
    if not (v["dte"].is_integer() and limits.min_dte <= v["dte"] <= limits.max_dte):
        return False
    spread = (v["ask"] - v["bid"]) / ((v["ask"] + v["bid"]) / 2)
    if not (0 <= v["relative_spread"] <= limits.max_relative_spread
            and spread <= limits.max_relative_spread):
        return False
    if not (v["open_interest"].is_integer() and v["open_interest"] >= limits.min_open_interest
            and v["volume"].is_integer() and v["volume"] >= limits.min_daily_volume):
        return False
    if _num(row.get("iv_solved")) is None or row["iv_solved"] <= 0:
        return False
    # Preserve missing optional Greeks as unknown; reject corrupt present ones.
    for key in ("iv_solved", "gamma", "theta_per_day", "vega"):
        if row.get(key) is not None and _num(row[key]) is None:
            return False
    return True


def selection_metrics(row: dict[str, Any], target_abs_delta: float,
                      policy: ContractSelectionPolicy = DEFAULT_POLICY) -> dict[str, Any]:
    target = _num(target_abs_delta)
    if target is None or not 0 < target <= 1:
        raise ValueError("target_abs_delta must be finite, greater than zero and at most one")
    delta, ask, cost, theta, dte = (_num(row.get(key)) for key in
                                  ("delta", "ask", "round_trip_cost_1x", "theta_per_day", "dte"))
    gap = abs(abs(delta) - target) if delta is not None else None
    premium = ask if ask is not None and ask > 0 else None
    return {
        "target_abs_delta": target,
        "delta_gap": gap,
        "inside_delta_tolerance": gap is not None and gap <= policy.delta_tolerance + 1e-12,
        "round_trip_cost_pct_premium": cost / premium / 100 if premium and cost is not None else None,
        "theta_pct_premium_per_day": max(-theta, 0.0) / premium if premium and theta is not None else None,
        "signed_theta_pct_premium_per_day": theta / premium if premium and theta is not None else None,
        "dte": dte,
        "dte_distance_from_preferred": abs(dte - policy.preferred_dte) if dte is not None else None,
        **{key: _num(row.get(key)) for key in ("relative_spread", "open_interest", "volume",
                                               "iv_solved", "gamma", "vega")},
        "contract_multiplier_assumption": 100,
        "quote_age_status": "UNVERIFIED",
        "policy": policy.to_dict(),
    }


def identity(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("type", "expiration", "strike")}


def ranking_key(row: dict[str, Any], target_abs_delta: float,
                policy: ContractSelectionPolicy = DEFAULT_POLICY) -> tuple:
    m = selection_metrics(row, target_abs_delta, policy)
    def val(key):
        return m[key] if m[key] is not None else inf
    end = (str(row.get("expiration", "")), _num(row.get("strike")) or 0,
           str(row.get("type", "")), str(row.get("contract_symbol", "")))
    if policy.mode == "delta":
        return (val("delta_gap"), val("relative_spread"), *end)
    economics = (val("round_trip_cost_pct_premium"), val("delta_gap"),
                 val("theta_pct_premium_per_day"), val("dte_distance_from_preferred"),
                 val("relative_spread"), -(m["open_interest"] or 0), -(m["volume"] or 0))
    if m["inside_delta_tolerance"]:
        return (0, *economics, *end)
    return (1, val("delta_gap"), *economics, *end)


def rank_contracts(rows: Sequence[dict[str, Any]], target_abs_delta: float,
                   policy: ContractSelectionPolicy = DEFAULT_POLICY) -> list[dict[str, Any]]:
    """Rank already eligible rows. The pick generator enforces eligibility first."""
    return sorted(rows, key=lambda row: ranking_key(row, target_abs_delta, policy))


def selection_audit(rows: Sequence[dict[str, Any]], target_abs_delta: float,
                    policy: ContractSelectionPolicy = DEFAULT_POLICY) -> dict[str, Any]:
    ranked = rank_contracts(rows, target_abs_delta, policy)
    def describe(row):
        return {"contract": identity(row), "metrics": selection_metrics(row, target_abs_delta, policy)}
    return {
        "policy": policy.to_dict(), "eligible_count": len(ranked),
        "top_candidates": [describe(row) for row in ranked[:5]],
        "alternatives_truncated": len(ranked) > 5,
        "baseline_contract": identity(rank_contracts(rows, target_abs_delta,
                                                     replace(policy, mode="delta"))[0]) if rows else None,
        "cost_aware_contract": identity(rank_contracts(rows, target_abs_delta,
                                                       replace(policy, mode="cost_aware"))[0]) if rows else None,
        "note": "Alternative identities are not independently resolved trades or evidence of edge.",
    }
