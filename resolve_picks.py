#!/usr/bin/env python3
"""
Score a frozen pick file against what actually happened.

    python resolve_picks.py picks/picks_2026-09-03_20260903-160000.json

The separate-resolver half of the roadmap's Phase 6. It is a separate program on
purpose: the thing that decides whether a prediction was right must not be the
thing that made it, and it must run against a file it cannot edit.

FIRST THING IT DOES is re-hash the picks and compare against the digest recorded
when they were frozen. A mismatch voids the record and the run stops. That check
is the whole reason the forward log is worth more than a backtest.

HOW A POSITION IS MARKED
Preference order, and every row says which was used:
  MARKET   a chain snapshot taken on or after the assessment date containing the
           exact contract. A real observed quote. Fetch daily with --chains and
           you get these.
  MODELLED Black-Scholes re-mark using the later underlying close and the IV
           solved at entry. Honest but it assumes volatility did not move, which
           is exactly the assumption most likely to be wrong after a real move.
           Reported separately and never mixed into the market-marked figures.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MP_V01_DIR = HERE / "claude" / "app" / "mp_v01"
DEFAULT_DATA_DIR = MP_V01_DIR / "data_store"

sys.path.insert(0, str(MP_V01_DIR / "src"))

from backtest.costs import CostModel                      # noqa: E402
from options.greeks import black_scholes_price, years_to_expiry  # noqa: E402
from strategy.picks import verify                          # noqa: E402

import excel_report as ex                                  # noqa: E402


def bars_after(rows, decision_date):
    return [r for r in sorted(rows, key=lambda r: r.get("date") or "")
            if r.get("date") and r["date"] > decision_date and r.get("close") is not None]


def market_mark(chain_doc, contract):
    """Exact contract in a later snapshot, if one was captured."""
    if not chain_doc:
        return None
    for c in chain_doc.get("contracts", []):
        if (c.get("type") == contract["type"]
                and str(c.get("expiration")) == str(contract["expiration"])
                and abs(float(c.get("strike") or -1) - float(contract["strike"])) < 1e-9
                and c.get("status") == "OK" and c.get("bid") is not None):
            return c
    return None


def resolve_one(pick, bars, later_chain, costs):
    """Mark one pick. Returns a row with the mark method stated."""
    c = pick["contract"]
    horizon = pick["exit_policy"]["horizon_trading_days"]
    forward = bars_after(bars, pick["decision_date"])
    out = {"variant": pick["variant"], "ticker": pick["ticker"],
           "action": pick["action"], "direction": pick["direction"],
           "composite_score": pick["composite_score"],
           "contract": f"{c['expiration']} {c['strike']:g} {c['type']}",
           "entry": pick["entry_fill_estimate"]}

    if len(forward) < horizon:
        out.update(status="NOT_YET_RESOLVABLE",
                   detail=f"{len(forward)} of {horizon} trading days elapsed")
        return out

    assess = forward[horizon - 1]
    entry_spot = c["underlying_close"]
    exit_spot = assess["close"]
    out["assessment_date"] = assess["date"]
    out["underlying_move_pct"] = exit_spot / entry_spot - 1.0 if entry_spot else None

    # Was the DIRECTIONAL call right? Independent of option mechanics, and the
    # thing the label contract would score.
    if out["underlying_move_pct"] is not None:
        up = out["underlying_move_pct"] > 0
        out["direction_correct"] = (up and pick["direction"] == "BULLISH") or \
                                   ((not up) and pick["direction"] == "BEARISH")

    quote = market_mark(later_chain, c)
    if quote is not None:
        exit_price = costs.option_fill_price(float(quote["bid"]), float(quote["ask"]), "SELL")
        out["mark_method"] = "MARKET"
    else:
        T = years_to_expiry(assess["date"], c["expiration"])
        if T is None or not c.get("iv_solved"):
            out.update(status="UNMARKABLE",
                       detail="no later snapshot with this contract, and it cannot be "
                              "re-priced (expired, or no entry IV)")
            return out
        theo = black_scholes_price(float(exit_spot), float(c["strike"]), T,
                                   0.04, float(c["iv_solved"]), 0.0, c["type"])
        if theo is None:
            out.update(status="UNMARKABLE", detail="Black-Scholes re-mark failed")
            return out
        exit_price = theo
        out["mark_method"] = "MODELLED"
        out["mark_caveat"] = "assumes IV unchanged since entry"

    entry = float(pick["entry_fill_estimate"])
    out["exit_price"] = round(exit_price, 4)
    gross = (exit_price - entry) * 100.0
    fees = 2 * (costs.option_commission_per_contract + costs.option_exchange_fees_per_contract)
    out["pnl_per_contract"] = round(gross - fees, 2)
    out["return_on_premium"] = round((gross - fees) / (entry * 100.0), 4) if entry else None
    out["status"] = "RESOLVED"

    # Did the pre-registered secondary rules trigger before the time stop?
    rp = out["return_on_premium"]
    pol = pick["exit_policy"]
    if rp is not None:
        if rp >= pol["profit_target_pct"]:
            out["secondary_rule_at_horizon"] = "PROFIT_TARGET_MET"
        elif rp <= pol["stop_loss_pct"]:
            out["secondary_rule_at_horizon"] = "STOP_LOSS_HIT"
        else:
            out["secondary_rule_at_horizon"] = "NEITHER"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("pick_file")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    a = ap.parse_args(argv)

    path = Path(a.pick_file).expanduser()
    if not path.is_file():
        print(f"No such pick file: {path}")
        return 1
    frozen = json.loads(path.read_text(encoding="utf-8"))

    print("=" * 78)
    print(f"MONEY PRINTER - resolving {path.name}")
    print("=" * 78)
    print(f"Decision date : {frozen['decision_date']}")
    print(f"Generated     : {frozen['generated_utc']}")

    if not verify(frozen):
        print("\n*** INTEGRITY CHECK FAILED ***")
        print("The picks do not hash to the digest recorded when they were frozen.")
        print("This file was modified after generation. The record is void; scoring it")
        print("would be worse than not scoring it, because the result would look real.")
        return 2
    print("Integrity     : OK - picks match their recorded SHA-256")

    data = ex.collect(Path(a.data_dir).expanduser().resolve())
    costs = CostModel()
    proposed = [p for p in frozen["picks"] if p["action"] != "ABSTAIN"]
    if not proposed:
        print("\nNo proposals in this file - every variant abstained.")
        return 0

    results = []
    for p in proposed:
        bars = data["rows"].get(p["ticker"], [])
        chain = None
        cf = data.get("chain_files", {}).get(p["ticker"])
        if cf:
            doc = json.loads(Path(cf).read_text(encoding="utf-8"))
            if str(doc.get("snapshot_time_utc", ""))[:10] > p["decision_date"]:
                chain = doc
        results.append(resolve_one(p, bars, chain, costs))

    print("\n" + "-" * 78)
    print(f"{'variant':<22}{'tkr':<6}{'dir':<9}{'move':>8}{'ok':>4}{'ret':>9}{'mark':>10}")
    print("-" * 78)
    for r in results:
        if r["status"] != "RESOLVED":
            print(f"{r['variant']:<22}{r['ticker']:<6}{r['direction']:<9}"
                  f"{'—':>8}{'—':>4}{'—':>9}{r['status']:>10}   {r.get('detail','')}")
            continue
        print(f"{r['variant']:<22}{r['ticker']:<6}{r['direction']:<9}"
              f"{r['underlying_move_pct']:>+8.2%}"
              f"{('Y' if r['direction_correct'] else 'n'):>4}"
              f"{r['return_on_premium']:>+9.1%}{r['mark_method']:>10}")

    resolved = [r for r in results if r["status"] == "RESOLVED"]
    if resolved:
        hits = sum(1 for r in resolved if r["direction_correct"])
        avg = sum(r["return_on_premium"] for r in resolved) / len(resolved)
        print("-" * 78)
        print(f"Resolved {len(resolved)} of {len(results)}   "
              f"direction correct {hits}/{len(resolved)} ({hits/len(resolved):.0%})   "
              f"mean return on premium {avg:+.1%}")
        by_variant = {}
        for r in resolved:
            by_variant.setdefault(r["variant"], []).append(r)
        print("\nBy variant:")
        for v, rs in sorted(by_variant.items()):
            h = sum(1 for r in rs if r["direction_correct"])
            m = sum(r["return_on_premium"] for r in rs) / len(rs)
            print(f"  {v:<22} {h}/{len(rs)} correct   mean {m:+.1%}")

        modelled = sum(1 for r in resolved if r["mark_method"] == "MODELLED")
        if modelled:
            print(f"\n  NOTE: {modelled} of {len(resolved)} marks are MODELLED, not observed "
                  f"quotes.\n  They assume IV was unchanged since entry, which after a real "
                  f"move is\n  the assumption most likely to be wrong. Fetch daily with "
                  f"--chains to\n  get market marks instead.")

    print("\n" + "=" * 78)
    print(f"{len(resolved)} resolved observation(s). The pre-registration in README.md asks")
    print("for >= 200 non-overlapping decisions before any of this means anything.")
    print("A handful of resolved picks is a sample size of a handful.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
