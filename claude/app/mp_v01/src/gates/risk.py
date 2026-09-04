"""
Deterministic risk gates.

These sit OUTSIDE every language model. No confidence score, no persuasive
rationale, and no agent consensus can override them. A model may only ever
propose; this module decides.

Output is one of PASS / WATCH / PAPER_TRADE_CANDIDATE. There is deliberately no code path
that emits a live order.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class Decision(str, Enum):
    PASS = "PASS"                # do nothing; not demonstrably positive expectancy
    WATCH = "WATCH"              # interesting, insufficient evidence or bad economics
    PAPER_TRADE_CANDIDATE = "PAPER_TRADE_CANDIDATE"  # nominated for simulation only.
                                                     # NOT an authorization. Never a live order.


@dataclass(frozen=True)
class RiskLimits:
    min_independent_events: int = 2       # syndication-collapsed, not raw article count
    min_evidence_confidence: float = 0.60
    max_position_pct: float = 0.02        # of portfolio, per position
    max_portfolio_heat_pct: float = 0.06  # total simultaneous risk
    max_open_positions: int = 5
    min_dte: int = 21
    max_dte: int = 60
    max_relative_spread: float = 0.10
    min_open_interest: int = 500
    min_daily_volume: int = 50
    require_defined_risk: bool = True
    min_edge_after_costs: float = 0.0     # must beat costs, not just be directionally right


@dataclass
class GateResult:
    decision: Decision
    reasons: list[str] = field(default_factory=list)
    failed_gates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reasons": self.reasons,
            "failed_gates": self.failed_gates,
        }


def evaluate(candidate: dict, limits: RiskLimits = RiskLimits()) -> GateResult:
    """
    Pure function. Same input always yields the same decision, and the decision
    is fully explained by `failed_gates`.

    Unknown inputs are treated as failures, never as neutral. Absence of evidence
    is not evidence of safety.
    """
    failed: list[str] = []
    reasons: list[str] = []

    def _bad_numeric(v) -> bool:
        # NaN comparisons are always False (`nan > x` and `nan < x` both fail),
        # so an unguarded NaN/Inf silently slides past every threshold check
        # below instead of failing the gate. Caught here so it can never do that.
        return isinstance(v, float) and (v != v or math.isinf(v))

    def _is_number(v) -> bool:
        # A candidate arriving from JSON, a model response or a spreadsheet can
        # carry "35" instead of 35. Comparing that to a threshold raises
        # TypeError, and an exception is not a decision - whatever called this
        # gate then either crashes or catches broadly, and a broad catch around
        # a risk gate is how PASS quietly becomes "skipped".
        # bool is an int subclass; True as a DTE or a position size is nonsense.
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    def _reject_type(key, v) -> None:
        failed.append(f"invalid_type:{key}")
        reasons.append(
            f"{key} is {type(v).__name__}, not a number — treated as failing, fail-closed"
        )

    def need(key):
        v = candidate.get(key)
        if v is None:
            failed.append(f"missing:{key}")
            return None
        if not _is_number(v):
            _reject_type(key, v)
            return None
        if _bad_numeric(v):
            failed.append(f"invalid_numeric:{key}")
            reasons.append(f"{key} is NaN or infinite — treated as failing, fail-closed")
            return None
        return v

    # --- Evidence gates -------------------------------------------------
    n_events = need("independent_events")
    if n_events is not None and n_events < limits.min_independent_events:
        failed.append("insufficient_independent_evidence")
        reasons.append(
            f"{n_events} independent information event(s); "
            f"{limits.min_independent_events} required after syndication collapse"
        )

    conf = need("evidence_confidence")
    if conf is not None and conf < limits.min_evidence_confidence:
        failed.append("low_evidence_confidence")
        reasons.append(f"confidence {conf:.2f} < {limits.min_evidence_confidence:.2f}")

    if candidate.get("unresolved_contradictions"):
        failed.append("unresolved_contradictions")
        reasons.append(
            f"{len(candidate['unresolved_contradictions'])} contradiction(s) unresolved"
        )

    if candidate.get("cutoff_violations"):
        failed.append("cutoff_violation")
        reasons.append("evidence postdates the decision timestamp (lookahead)")

    # --- Contract economics ---------------------------------------------
    dte = need("dte")
    if dte is not None and not (limits.min_dte <= dte <= limits.max_dte):
        failed.append("dte_out_of_band")
        reasons.append(f"{dte} DTE outside {limits.min_dte}-{limits.max_dte}")

    rel_spread = need("relative_spread")
    if rel_spread is not None and rel_spread > limits.max_relative_spread:
        failed.append("spread_too_wide")
        reasons.append(f"spread {rel_spread:.1%} > {limits.max_relative_spread:.0%}")

    oi = need("open_interest")
    if oi is not None and oi < limits.min_open_interest:
        failed.append("insufficient_open_interest")
        reasons.append(f"OI {oi} < {limits.min_open_interest}")

    vol = need("daily_volume")
    if vol is not None and vol < limits.min_daily_volume:
        failed.append("insufficient_volume")
        reasons.append(f"volume {vol} < {limits.min_daily_volume}")

    if limits.require_defined_risk and not candidate.get("defined_risk", False):
        failed.append("undefined_risk_structure")
        reasons.append("structure has undefined/unbounded loss")

    # --- Expectancy AFTER costs -----------------------------------------
    edge = need("expected_edge_after_costs")
    if edge is not None and edge <= limits.min_edge_after_costs:
        failed.append("no_edge_after_costs")
        reasons.append(f"edge after costs {edge:+.4f} is not positive")

    # --- Sizing ----------------------------------------------------------
    size = candidate.get("position_pct")
    if size is not None:
        if not _is_number(size):
            _reject_type("position_pct", size)
        elif _bad_numeric(size):
            failed.append("invalid_numeric:position_pct")
            reasons.append("position_pct is NaN or infinite — treated as failing, fail-closed")
        elif size > limits.max_position_pct:
            failed.append("position_too_large")
            reasons.append(f"size {size:.1%} > {limits.max_position_pct:.1%}")

    heat = candidate.get("portfolio_heat_pct")
    if heat is not None:
        if not _is_number(heat):
            _reject_type("portfolio_heat_pct", heat)
        elif _bad_numeric(heat):
            failed.append("invalid_numeric:portfolio_heat_pct")
            reasons.append("portfolio_heat_pct is NaN or infinite — treated as failing, fail-closed")
        elif heat > limits.max_portfolio_heat_pct:
            failed.append("portfolio_heat_exceeded")
            reasons.append(f"heat {heat:.1%} > {limits.max_portfolio_heat_pct:.1%}")

    open_n = candidate.get("open_positions")
    if open_n is not None:
        if not _is_number(open_n):
            _reject_type("open_positions", open_n)
        elif _bad_numeric(open_n):
            failed.append("invalid_numeric:open_positions")
            reasons.append("open_positions is NaN or infinite — treated as failing, fail-closed")
        elif open_n >= limits.max_open_positions:
            failed.append("max_positions_reached")
            reasons.append(f"{open_n} open >= {limits.max_open_positions}")

    # --- Verdict ----------------------------------------------------------
    if not failed:
        return GateResult(Decision.PAPER_TRADE_CANDIDATE,
                          reasons or ["all gates passed"], [])

    hard = {"cutoff_violation", "no_edge_after_costs", "undefined_risk_structure",
            "position_too_large", "portfolio_heat_exceeded", "max_positions_reached"}
    if any(f in hard or f.startswith("missing:") or f.startswith("invalid_numeric:")
           or f.startswith("invalid_type:") for f in failed):
        return GateResult(Decision.PASS, reasons, failed)

    return GateResult(Decision.WATCH, reasons, failed)
