"""
Turn component scores plus an option chain into a frozen, hashed pick list.

This is the generator half of the roadmap's Phase 6: "scheduled runs producing
frozen, hashed predictions; separate resolver scoring after 5 days." The
freezing is the point. A prediction you can still edit after seeing the outcome
is not a prediction.

WHAT A PICK IS AND IS NOT
A pick here is a HYPOTHESIS nominated for paper simulation. It is not a
recommendation, not gate-approved, and not evidence of edge. gates/risk.py is
run on every pick and its verdict is recorded verbatim - it returns PASS,
meaning do nothing, because a chain snapshot plus an unvalidated component score
contains no independent evidence count and no measured post-cost edge, and the
gate fails closed on what it is not told.

That is not a bug to route around. It is the loop working as designed: the
forward paper record is what will eventually PRODUCE the edge estimate the gate
needs. Until then the gate cannot honestly approve anything, and the pick file
says so on every row.

EXITS ARE PRE-REGISTERED
The exit rules are written into the file at generation time, before any outcome
is known. Deciding when to close after watching the position is how a losing
trade becomes "still developing" and a winner becomes "I knew it." The primary
assessment is at the label contract's own horizon so paper results stay
comparable with what the model is scored against.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Sequence

from gates.risk import RiskLimits, evaluate as evaluate_gate
from labels.contract import HORIZON_TRADING_DAYS
from strategy.variants import Variant, score as score_variant

PICK_CONTRACT_VERSION = "0.1.0"

# Required keys on an option row handed to this module. Stated so the coupling
# to whatever produced the chain is explicit rather than discovered at runtime.
REQUIRED_OPTION_KEYS = (
    "type", "expiration", "dte", "strike", "bid", "ask", "mid", "delta",
    "relative_spread", "open_interest", "volume", "model_status",
    "liquidity_screen", "round_trip_cost_1x", "underlying_close",
)


@dataclass(frozen=True)
class ExitPolicy:
    """Pre-registered. Frozen into every pick file before any outcome is known.

    horizon_trading_days is the PRIMARY assessment point and deliberately equals
    the label contract's horizon, so a paper result is directly comparable with
    the target the model would be scored on.

    The profit target and stop are SECONDARY and recorded so the record can
    answer a second, different question: what a disciplined trader following
    fixed rules would have realised, which is path-dependent and not the same as
    whether the directional call was right.

    min_dte_exit mirrors RiskLimits.min_dte. Below it, theta and gamma both
    accelerate and the contract stops behaving like the one that was chosen.
    """
    horizon_trading_days: int = HORIZON_TRADING_DAYS
    profit_target_pct: float = 0.50
    stop_loss_pct: float = -0.50
    min_dte_exit: int = RiskLimits().min_dte

    def describe(self) -> list[str]:
        return [
            f"PRIMARY: mark to market after {self.horizon_trading_days} trading days "
            f"and score the directional call. This matches the label contract horizon.",
            f"SECONDARY (path-dependent, recorded separately): close at "
            f"{self.profit_target_pct:+.0%} or {self.stop_loss_pct:+.0%} of premium paid, "
            f"whichever comes first.",
            f"HARD EXIT: close if days-to-expiry falls below {self.min_dte_exit}, "
            f"whatever the P&L.",
            "These were fixed before the outcome was known. Changing them mid-flight "
            "invalidates the record.",
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_contract(option_rows: Sequence[dict[str, Any]], *, kind: str,
                    target_abs_delta: float) -> tuple[dict | None, str]:
    """Closest liquid contract to the variant's delta target.

    Returns (row, reason). A None row always carries a reason, so an abstention
    is never silent.
    """
    missing_keys = [k for k in REQUIRED_OPTION_KEYS
                    if option_rows and k not in option_rows[0]]
    if missing_keys:
        return None, f"option rows are missing required keys: {', '.join(missing_keys)}"

    candidates = [r for r in option_rows
                  if r.get("type") == kind
                  and r.get("model_status") == "OK"
                  and r.get("liquidity_screen") == "PASS"
                  and isinstance(r.get("delta"), (int, float))]
    if not candidates:
        n_kind = sum(1 for r in option_rows if r.get("type") == kind)
        return None, (f"no {kind} passed the liquidity screen with modellable Greeks "
                      f"({n_kind} {kind}s in the snapshot)")

    best = min(candidates, key=lambda r: (abs(abs(r["delta"]) - target_abs_delta),
                                          r.get("relative_spread") or 9.9))
    return best, "closest liquid strike to the variant's delta target"


def breakeven_move_pct(row: dict[str, Any]) -> float | None:
    """Underlying move needed just to cover round-trip execution cost.

    cost / (|delta| x 100) is the dollar move the underlying must make for the
    contract to gain the cost back, to first order. Expressed as a fraction of
    spot. First-order only: it ignores gamma, and it ignores theta, so the real
    hurdle over a five-day hold is HIGHER than this figure, not lower.
    """
    delta, cost, spot = row.get("delta"), row.get("round_trip_cost_1x"), row.get("underlying_close")
    if not all(isinstance(v, (int, float)) for v in (delta, cost, spot)):
        return None
    if not delta or not spot:
        return None
    return abs(cost / (abs(delta) * 100.0) / spot)


def build_rationale(ticker: str, variant: Variant, composite: float,
                    comps: dict[str, Any], row: dict[str, Any],
                    breakeven: float | None) -> str:
    """One paragraph, assembled from the numbers actually used.

    Every figure quoted here is computed above, not asserted. The closing
    sentence is not boilerplate - it is the single most important thing about
    the pick, and it is stated on every one because it is true of every one.
    """
    raw = comps.get("raw", {})

    def pct(v):
        """Signed: a return of -5% and +5% are different claims."""
        return "unknown" if v is None else f"{v:+.1%}"

    def mag(v):
        """Unsigned: a volatility is a magnitude, and '+1.0%' reads as a change."""
        return "unknown" if v is None else f"{v:.1%}"

    drivers = sorted(variant.weights.items(), key=lambda kv: -abs(kv[1]))[:3]
    driver_text = ", ".join(
        f"{k.replace('_', ' ')} {comps['scaled'][k]:+.2f}" for k, _w in drivers
        if comps["scaled"].get(k) is not None)

    direction = "bullish" if composite > 0 else "bearish"
    kind = row["type"].lower()

    parts = [
        f"The {variant.name} variant scores {ticker} {composite:+.2f} ({direction}), "
        f"driven by {driver_text}.",
        f"Underlying context as of {comps.get('last_available_date')}: "
        f"20-day return {pct(raw.get('return_20d'))}, "
        f"60-day return {pct(raw.get('return_60d'))}, "
        f"close {pct(raw.get('distance_from_sma50'))} versus its 50-day average, "
        f"realised volatility {mag(raw.get('realised_vol_20d'))} annualised, "
        f"{pct(raw.get('drawdown_from_252d_high'))} from its 252-day high.",
        f"The proposal is the {row['expiration']} {row['strike']:g} {kind} at "
        f"{row['delta']:+.2f} delta ({row['dte']} DTE), the closest liquid strike to this "
        f"variant's {variant.target_abs_delta:.2f} delta target, quoted "
        f"{row['bid']:.2f}/{row['ask']:.2f} — a {row['relative_spread']:.1%} spread with "
        f"{row['open_interest']:,} open interest and {row['volume']:,} contracts traded.",
    ]
    if breakeven is not None:
        parts.append(
            f"Round-trip execution cost is ${row['round_trip_cost_1x']:.2f} per contract, so "
            f"{ticker} must move about {breakeven:.1%} in the chosen direction simply to break "
            f"even on costs — before any theta decay over the holding period, which makes the "
            f"real hurdle higher still.")
    parts.append(
        "No edge has been demonstrated for any of these components: none has a measured rank "
        "information coefficient against forward excess return in this project. This is a "
        "hypothesis logged for forward measurement, not a validated signal, and the risk gate "
        "declines to approve it for exactly that reason.")
    return " ".join(parts)


def generate_picks(
    decision_date: str,
    per_ticker: dict[str, dict[str, Any]],
    *,
    variants: Sequence[Variant],
    exit_policy: ExitPolicy,
    limits: RiskLimits | None = None,
) -> list[dict[str, Any]]:
    """One pick per (variant, ticker) that clears its conviction floor.

    per_ticker maps ticker -> {"components": <components.compute output>,
                               "option_rows": [...]}.
    Every abstention is recorded with its reason rather than dropped, so the run
    is auditable: "the strategy proposed nothing" and "the data was unusable"
    are different statements.
    """
    limits = limits or RiskLimits()
    out: list[dict[str, Any]] = []

    for variant in variants:
        for ticker in sorted(per_ticker):
            payload = per_ticker[ticker]
            comps = payload.get("components") or {}
            rows = payload.get("option_rows") or []
            base = {
                "decision_date": decision_date,
                "variant": variant.name,
                "variant_description": variant.description,
                "weights": variant.normalised_weights(),
                "ticker": ticker,
                "contract_version": PICK_CONTRACT_VERSION,
            }

            composite, missing = score_variant(variant, comps.get("scaled", {}))
            if composite is None:
                out.append({**base, "action": "ABSTAIN", "composite_score": None,
                            "reason": f"insufficient history for: {', '.join(missing)}"})
                continue

            base["composite_score"] = round(composite, 4)
            base["components_raw"] = comps.get("raw", {})
            base["components_scaled"] = comps.get("scaled", {})

            if abs(composite) < variant.conviction_floor:
                out.append({**base, "action": "ABSTAIN",
                            "reason": f"conviction {abs(composite):.2f} below the variant's "
                                      f"{variant.conviction_floor:.2f} floor"})
                continue

            kind = "CALL" if composite > 0 else "PUT"
            row, why = select_contract(rows, kind=kind,
                                       target_abs_delta=variant.target_abs_delta)
            if row is None:
                out.append({**base, "action": "ABSTAIN", "reason": why})
                continue

            be = breakeven_move_pct(row)
            verdict = evaluate_gate({
                "dte": row.get("dte"), "relative_spread": row.get("relative_spread"),
                "open_interest": row.get("open_interest"), "daily_volume": row.get("volume"),
                "defined_risk": True,   # a long single-leg option: loss is capped at premium
            }, limits)

            out.append({
                **base,
                "action": f"PAPER_LONG_{kind}",
                "direction": "BULLISH" if composite > 0 else "BEARISH",
                "contract": {
                    "type": row["type"], "expiration": row["expiration"],
                    "strike": row["strike"], "dte": row["dte"],
                    "bid": row["bid"], "ask": row["ask"], "mid": row["mid"],
                    "delta": row["delta"], "gamma": row.get("gamma"),
                    "theta_per_day": row.get("theta_per_day"), "vega": row.get("vega"),
                    "iv_solved": row.get("iv_solved"),
                    "relative_spread": row["relative_spread"],
                    "open_interest": row["open_interest"], "volume": row["volume"],
                    "underlying_close": row["underlying_close"],
                    "underlying_close_date": row.get("underlying_close_date"),
                },
                "selection_reason": why,
                "entry_fill_estimate": row["ask"],   # a buyer crosses the spread
                "round_trip_cost_1x": row["round_trip_cost_1x"],
                "breakeven_move_pct": round(be, 6) if be is not None else None,
                "exit_policy": exit_policy.to_dict(),
                "gate_decision": verdict.decision.value,
                "gate_failed": verdict.failed_gates,
                "edge_status": "NOT_DEMONSTRATED",
                "rationale": build_rationale(ticker, variant, composite, comps, row, be),
            })
    return out


def freeze(decision_date: str, picks: Sequence[dict[str, Any]], *,
           exit_policy: ExitPolicy, universe: Sequence[str],
           generated_utc: str, source_files: dict[str, Any]) -> dict[str, Any]:
    """Wrap picks in an envelope carrying a hash of their exact content.

    The hash is over the canonical JSON of the picks alone. Re-running the
    resolver later recomputes it; if it does not match, the file was edited
    after the fact and the record is void. That is the entire mechanism that
    makes a forward paper log worth more than a backtest.
    """
    canonical = json.dumps(picks, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    proposed = [p for p in picks if p["action"] != "ABSTAIN"]
    return {
        "schema": "moneyprinter.picks",
        "contract_version": PICK_CONTRACT_VERSION,
        "decision_date": decision_date,
        "generated_utc": generated_utc,
        "universe": list(universe),
        "n_picks": len(proposed),
        "n_abstentions": len(picks) - len(proposed),
        "exit_policy": exit_policy.to_dict(),
        "exit_policy_plain_english": exit_policy.describe(),
        "edge_status": "NOT_DEMONSTRATED",
        "disclaimer": (
            "Paper/simulation only. These are hypotheses nominated for forward "
            "measurement, not recommendations and not gate-approved. No component "
            "used here has a measured rank information coefficient against forward "
            "excess return. No live order path exists anywhere in this project."
        ),
        "source_files": source_files,
        "picks_sha256": digest,
        "picks": list(picks),
    }


def verify(frozen: dict[str, Any]) -> bool:
    """True if the picks still hash to what was recorded when they were frozen."""
    canonical = json.dumps(frozen.get("picks", []), sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest() == frozen.get("picks_sha256")


def approximate_assessment_date(decision_date: str, trading_days: int) -> str | None:
    """Calendar date roughly `trading_days` sessions out, for a human diary.

    Approximate on purpose and named so. The resolver counts ACTUAL trading bars
    rather than trusting this, because holidays make any calendar arithmetic
    wrong a few times a year and a silently wrong assessment date would score
    the wrong day.
    """
    try:
        d = date.fromisoformat(decision_date[:10])
    except (ValueError, TypeError):
        return None
    added = 0
    while added < trading_days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.isoformat()
