"""
Score a frozen pick against what actually happened.

Lives in the core rather than beside a CLI because two callers need it and they
must agree: resolve_picks.py (the terminal report) and the Excel pick-history
tab. A second implementation would eventually disagree with the first, and the
disagreement would surface as two different track records for the same picks.

HOW A POSITION IS CLOSED
The exit rules were pre-registered at generation. This module walks FORWARD DAY
BY DAY from the decision date and closes the position the first time a rule
fires, rather than only looking at the horizon:

    DTE_FLOOR      days-to-expiry fell below the policy floor
    PROFIT_TARGET  return on premium reached the target
    STOP_LOSS      return on premium reached the stop
    TIME_STOP      none of the above fired before the horizon

Checking only the horizon would silently convert every stop-out into a
round trip and report a loss that a disciplined trader would never have taken -
and, worse, would report gains on positions that had already been stopped out.

TWO ANSWERS, KEPT APART
`exit_*` fields answer "what would following the rules have returned?" - path
dependent. `horizon_*` fields answer "was the directional call right?" - the
question the label contract scores, measured at the horizon regardless of what
happened in between. They are different questions and are never merged.

MARKING
MARKET where a chain snapshot for that date contains the exact contract - a real
observed quote. MODELLED otherwise: Black-Scholes at that day's close using the
IV solved at entry. Modelled marks assume volatility never moved, which after a
real move is the assumption most likely to be wrong, so the method is recorded
on every row and the two are never averaged together.
"""
from __future__ import annotations

from typing import Any, Sequence

from backtest.costs import CostModel
from options.greeks import black_scholes_price, years_to_expiry

# Used only for the Black-Scholes fallback mark. Recorded in the output so a
# reader knows what produced a modelled number.
DEFAULT_MARK_RATE = 0.04


def bars_after(rows: Sequence[dict[str, Any]], decision_date: str) -> list[dict[str, Any]]:
    """Sessions strictly after the decision date, in order."""
    return [r for r in sorted(rows, key=lambda r: r.get("date") or "")
            if r.get("date") and r["date"] > decision_date and r.get("close") is not None]


def market_quote(chain_doc: dict[str, Any] | None, contract: dict[str, Any]):
    """The exact contract in a snapshot, or None."""
    if not chain_doc:
        return None
    for c in chain_doc.get("contracts", []):
        try:
            same_strike = abs(float(c.get("strike")) - float(contract["strike"])) < 1e-9
        except (TypeError, ValueError):
            continue
        if (c.get("type") == contract["type"]
                and str(c.get("expiration")) == str(contract["expiration"])
                and same_strike and c.get("status") == "OK"
                and c.get("bid") is not None and c.get("ask") is not None):
            return c
    return None


def mark_on(date_str: str, contract: dict[str, Any], spot: float,
            chains_by_date: dict[str, dict[str, Any]] | None,
            costs: CostModel, rate: float = DEFAULT_MARK_RATE):
    """(exit_price, method) for one date, or (None, reason) if unmarkable."""
    quote = market_quote((chains_by_date or {}).get(date_str), contract)
    if quote is not None:
        try:
            return costs.option_fill_price(float(quote["bid"]), float(quote["ask"]), "SELL"), "MARKET"
        except ValueError:
            pass          # unusable quote; fall through to the model
    T = years_to_expiry(date_str, contract.get("expiration"))
    iv = contract.get("iv_solved")
    if T is None or not iv:
        return None, "EXPIRED_OR_NO_ENTRY_IV"
    theo = black_scholes_price(float(spot), float(contract["strike"]), T, rate,
                               float(iv), 0.0, contract["type"])
    return (theo, "MODELLED") if theo is not None else (None, "REMARK_FAILED")


def _return_on_premium(exit_price: float, entry: float, costs: CostModel) -> float | None:
    if not entry:
        return None
    fees = 2 * (costs.option_commission_per_contract + costs.option_exchange_fees_per_contract)
    return ((exit_price - entry) * 100.0 - fees) / (entry * 100.0)


def resolve_pick(pick: dict[str, Any], bars: Sequence[dict[str, Any]],
                 chains_by_date: dict[str, dict[str, Any]] | None = None,
                 costs: CostModel | None = None,
                 rate: float = DEFAULT_MARK_RATE) -> dict[str, Any]:
    """One pick's outcome. Never raises on thin data; reports status instead."""
    costs = costs or CostModel()
    c = pick.get("contract") or {}
    pol = pick.get("exit_policy") or {}
    horizon = int(pol.get("horizon_trading_days") or 5)
    target = float(pol.get("profit_target_pct", 0.50))
    stop = float(pol.get("stop_loss_pct", -0.50))
    dte_floor = int(pol.get("min_dte_exit") or 21)
    entry = pick.get("entry_fill_estimate")

    out: dict[str, Any] = {
        "decision_date": pick.get("decision_date"),
        "variant": pick.get("variant"),
        "ticker": pick.get("ticker"),
        "direction": pick.get("direction"),
        "action": pick.get("action"),
        "composite_score": pick.get("composite_score"),
        "contract": (f"{c.get('expiration')} {c.get('strike'):g} {c.get('type')}"
                     if c.get("strike") is not None else None),
        "expiration": c.get("expiration"),
        "strike": c.get("strike"),
        "type": c.get("type"),
        "dte_at_entry": c.get("dte"),
        "delta_at_entry": c.get("delta"),
        "iv_at_entry": c.get("iv_solved"),
        "entry_fill": entry,
        "horizon_trading_days": horizon,
        "profit_target_pct": target,
        "stop_loss_pct": stop,
        "min_dte_exit": dte_floor,
        "status": "OPEN",
        "exit_trigger": None, "exit_date": None, "days_held": None,
        "exit_price": None, "exit_mark_method": None,
        "exit_return_on_premium": None, "exit_pnl_per_contract": None,
        "horizon_date": None, "underlying_move_pct": None,
        "direction_correct": None, "horizon_return_on_premium": None,
        "horizon_mark_method": None,
        "detail": None,
    }

    forward = bars_after(bars, pick.get("decision_date") or "")
    entry_spot = c.get("underlying_close")
    if not forward:
        out["detail"] = "no sessions recorded after the decision date yet"
        return out
    if not entry or not entry_spot:
        out.update(status="UNMARKABLE", detail="pick has no entry fill or entry spot")
        return out

    # Walk the path. Close on the first pre-registered rule that fires.
    for i, bar in enumerate(forward[:horizon], start=1):
        d, spot = bar["date"], bar["close"]
        price, method = mark_on(d, c, spot, chains_by_date, costs, rate)
        if price is None:
            out.update(status="UNMARKABLE", detail=f"could not mark on {d}: {method}")
            return out
        rop = _return_on_premium(price, float(entry), costs)
        # Actual calendar days left, computed from this bar's date. Decrementing
        # the entry DTE by elapsed trading days would drift by a day every
        # weekend and silently move the DTE_FLOOR exit.
        t_left = years_to_expiry(d, c.get("expiration"))
        dte_now = round(t_left * 365) if t_left is not None else None

        trigger = None
        if dte_now is not None and dte_now < dte_floor:
            trigger = "DTE_FLOOR"
        elif rop is not None and rop >= target:
            trigger = "PROFIT_TARGET"
        elif rop is not None and rop <= stop:
            trigger = "STOP_LOSS"
        elif i == horizon:
            trigger = "TIME_STOP"

        if trigger:
            fees = 2 * (costs.option_commission_per_contract
                        + costs.option_exchange_fees_per_contract)
            out.update(status="RESOLVED", exit_trigger=trigger, exit_date=d, days_held=i,
                       exit_price=round(price, 4), exit_mark_method=method,
                       exit_return_on_premium=round(rop, 4) if rop is not None else None,
                       exit_pnl_per_contract=round((price - float(entry)) * 100.0 - fees, 2))
            break
    else:
        out["detail"] = (f"{len(forward)} of {horizon} trading days elapsed; "
                         f"no exit rule has fired")
        return out

    # The horizon measurement, independent of how the position was closed. This
    # is what the label contract scores, so it is computed even when a stop
    # fired earlier - "was the call right" and "did the trade make money" are
    # different questions and both belong in the record.
    if len(forward) >= horizon:
        hb = forward[horizon - 1]
        out["horizon_date"] = hb["date"]
        out["underlying_move_pct"] = hb["close"] / float(entry_spot) - 1.0
        up = out["underlying_move_pct"] > 0
        out["direction_correct"] = ((up and pick.get("direction") == "BULLISH")
                                    or ((not up) and pick.get("direction") == "BEARISH"))
        hp, hm = mark_on(hb["date"], c, hb["close"], chains_by_date, costs, rate)
        if hp is not None:
            out["horizon_mark_method"] = hm
            hr = _return_on_premium(hp, float(entry), costs)
            out["horizon_return_on_premium"] = round(hr, 4) if hr is not None else None
    return out


def summarise(outcomes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-variant performance over resolved picks only.

    Open positions are excluded rather than counted as flat: a position with no
    outcome yet is not a zero, and averaging it in as one would drag every
    variant toward the middle and understate both winners and losers.
    """
    by: dict[str, list[dict[str, Any]]] = {}
    for o in outcomes:
        if o.get("status") == "RESOLVED":
            by.setdefault(o.get("variant") or "unknown", []).append(o)

    rows = []
    for variant, rs in sorted(by.items()):
        dirs = [r for r in rs if r.get("direction_correct") is not None]
        hits = sum(1 for r in dirs if r["direction_correct"])
        rets = [r["exit_return_on_premium"] for r in rs
                if r.get("exit_return_on_premium") is not None]
        modelled = sum(1 for r in rs if r.get("exit_mark_method") == "MODELLED")
        triggers = {}
        for r in rs:
            triggers[r.get("exit_trigger")] = triggers.get(r.get("exit_trigger"), 0) + 1
        rows.append({
            "variant": variant,
            "resolved": len(rs),
            "direction_scored": len(dirs),
            "direction_correct": hits,
            "direction_hit_rate": (hits / len(dirs)) if dirs else None,
            "mean_return_on_premium": (sum(rets) / len(rets)) if rets else None,
            "best_return": max(rets) if rets else None,
            "worst_return": min(rets) if rets else None,
            "wins": sum(1 for r in rets if r > 0),
            "losses": sum(1 for r in rets if r <= 0),
            "modelled_marks": modelled,
            "exit_triggers": ", ".join(f"{k}:{v}" for k, v in sorted(
                triggers.items(), key=lambda kv: str(kv[0]))),
        })
    return rows
