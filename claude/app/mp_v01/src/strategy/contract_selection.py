"""Auditable contract ranking for paper/research picks.

This module deliberately does NOT claim a learned optimal contract score. There
is not yet enough point-in-time options outcome data in this project to justify
one. Instead it applies a conservative lexicographic policy after the existing
hard liquidity/model gates have passed:

1. stay reasonably close to the strategy's target absolute delta;
2. minimize estimated round-trip execution drag as a fraction of premium;
3. minimize daily theta burden as a fraction of premium;
4. then prefer closer delta, middle-of-band DTE, tighter spread, and deeper
   displayed liquidity.

Every input used for ranking is returned as a metric and frozen into the pick so
future paper/historical outcomes can test whether these priorities were useful.
When enough observations exist, learned weights can replace this policy without
rewriting history.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import inf
from typing import Any, Sequence


@dataclass(frozen=True)
class ContractSelectionPolicy:
    delta_tolerance: float = 0.08
    preferred_dte: int = 40

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and value not in (inf, -inf) else None


def selection_metrics(row: dict[str, Any], target_abs_delta: float,
                      policy: ContractSelectionPolicy = ContractSelectionPolicy()) -> dict[str, Any]:
    """Return only observed/derived quantities used to compare eligible contracts."""
    delta = _num(row.get("delta"))
    ask = _num(row.get("ask"))
    cost = _num(row.get("round_trip_cost_1x"))
    theta = _num(row.get("theta_per_day"))
    dte = _num(row.get("dte"))

    delta_gap = abs(abs(delta) - target_abs_delta) if delta is not None else None
    execution_drag = (cost / (ask * 100.0)
                      if cost is not None and ask is not None and ask > 0 else None)
    theta_burden = (abs(theta) / ask
                    if theta is not None and ask is not None and ask > 0 else None)

    return {
        "target_abs_delta": target_abs_delta,
        "delta_gap": delta_gap,
        "inside_delta_tolerance": (delta_gap <= policy.delta_tolerance
                                   if delta_gap is not None else False),
        "round_trip_cost_pct_premium": execution_drag,
        "theta_pct_premium_per_day": theta_burden,
        "dte": int(dte) if dte is not None else None,
        "dte_distance_from_preferred": (abs(dte - policy.preferred_dte)
                                        if dte is not None else None),
        "relative_spread": _num(row.get("relative_spread")),
        "open_interest": _num(row.get("open_interest")),
        "volume": _num(row.get("volume")),
        "iv_solved": _num(row.get("iv_solved")),
        "gamma": _num(row.get("gamma")),
        "vega": _num(row.get("vega")),
        "policy": policy.to_dict(),
    }


def ranking_key(row: dict[str, Any], target_abs_delta: float,
                policy: ContractSelectionPolicy = ContractSelectionPolicy()) -> tuple:
    """Lower is better. Missing economics rank last rather than being invented."""
    m = selection_metrics(row, target_abs_delta, policy)
    return (
        0 if m["inside_delta_tolerance"] else 1,
        m["round_trip_cost_pct_premium"] if m["round_trip_cost_pct_premium"] is not None else inf,
        m["delta_gap"] if m["delta_gap"] is not None else inf,
        m["theta_pct_premium_per_day"] if m["theta_pct_premium_per_day"] is not None else inf,
        m["dte_distance_from_preferred"] if m["dte_distance_from_preferred"] is not None else inf,
        m["relative_spread"] if m["relative_spread"] is not None else inf,
        -m["open_interest"] if m["open_interest"] is not None else inf,
        -m["volume"] if m["volume"] is not None else inf,
    )


def rank_contracts(rows: Sequence[dict[str, Any]], target_abs_delta: float,
                   policy: ContractSelectionPolicy = ContractSelectionPolicy()) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: ranking_key(row, target_abs_delta, policy))
