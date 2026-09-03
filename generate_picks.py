#!/usr/bin/env python3
"""
Generate a frozen, hashed paper-pick list from the point-in-time data store.

    python generate_picks.py                          # every ticker in the store
    python generate_picks.py --tickers SPY,MSFT
    python generate_picks.py --variants momentum,reversion

Requires a fetch WITH option chains first:

    python claude/app/mp_v01/fetch_data.py --tickers SPY,QQQ,MSFT --chains

Writes picks/picks_<decision-date>_<timestamp>.json and prints the short list.
Score them later with:

    python resolve_picks.py picks/<that file>

WHAT THIS IS
The generator half of the roadmap's Phase 6. Each run produces predictions that
are frozen and hashed at the moment of writing, so they cannot be edited once
the outcome is known. That property - not the picks themselves - is what makes
a forward paper record worth more than any backtest in this repository.

WHAT THIS IS NOT
Not advice, not gate-approved, not evidence of edge. Every pick records the risk
gate's verdict verbatim, and that verdict is PASS - do nothing - because no
component used here has a measured rank information coefficient against forward
excess return. The picks are hypotheses. The forward record is the experiment.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MP_V01_DIR = HERE / "claude" / "app" / "mp_v01"
DEFAULT_DATA_DIR = MP_V01_DIR / "data_store"
DEFAULT_PICKS_DIR = HERE / "picks"

sys.path.insert(0, str(MP_V01_DIR / "src"))

from gates.risk import RiskLimits               # noqa: E402
from strategy import components                 # noqa: E402
from strategy.picks import (                    # noqa: E402
    ExitPolicy, approximate_assessment_date, freeze, generate_picks,
)
from strategy.variants import BY_NAME, VARIANTS  # noqa: E402

import excel_report as ex                        # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_PICKS_DIR))
    ap.add_argument("--tickers", default=None, help="comma-separated subset")
    ap.add_argument("--variants", default=None,
                    help=f"comma-separated subset of: {', '.join(BY_NAME)}")
    ap.add_argument("--decision-date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--risk-free-rate", type=float, default=ex.DEFAULT_RISK_FREE_RATE)
    a = ap.parse_args(argv)

    data_dir = Path(a.data_dir).expanduser().resolve()
    only = a.tickers.split(",") if a.tickers else None

    chosen = VARIANTS
    if a.variants:
        names = [v.strip() for v in a.variants.split(",") if v.strip()]
        unknown = [n for n in names if n not in BY_NAME]
        if unknown:
            ap.error(f"unknown variant(s): {', '.join(unknown)}. "
                     f"Available: {', '.join(BY_NAME)}")
        chosen = tuple(BY_NAME[n] for n in names)

    print("=" * 78)
    print(f"MONEY PRINTER - paper pick generation   decision date {a.decision_date}")
    print("=" * 78)

    data = ex.collect(data_dir, only, risk_free_rate=a.risk_free_rate)
    if not data["rows"]:
        print("\nNo bars in the store. Fetch first:")
        print("    python claude/app/mp_v01/fetch_data.py --tickers SPY,QQQ,MSFT --chains")
        return 1
    if not data.get("options"):
        print("\nBars are present but no option chain snapshots are.")
        print("Picks need a chain. Re-fetch with --chains:")
        print("    python claude/app/mp_v01/fetch_data.py --tickers SPY,QQQ,MSFT --chains")
        return 1

    per_ticker = {}
    for ticker, rows in data["rows"].items():
        per_ticker[ticker] = {
            "components": components.compute(rows, a.decision_date),
            "option_rows": data["options"].get(ticker, []),
        }

    policy = ExitPolicy()
    picks = generate_picks(a.decision_date, per_ticker, variants=chosen,
                           exit_policy=policy, limits=RiskLimits())

    frozen = freeze(
        a.decision_date, picks, exit_policy=policy,
        universe=sorted(data["rows"]),
        generated_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_files={"bars": data["files"], "chains": data["chain_files"],
                      "risk_free_rate": a.risk_free_rate},
    )

    proposed = [p for p in picks if p["action"] != "ABSTAIN"]
    assess = approximate_assessment_date(a.decision_date, policy.horizon_trading_days)

    print(f"\nUniverse      : {', '.join(sorted(data['rows']))}")
    print(f"Variants      : {', '.join(v.name for v in chosen)}")
    print(f"Proposed      : {len(proposed)}     Abstentions: {len(picks) - len(proposed)}")
    print(f"Assess around : {assess}  (approx; the resolver counts real trading bars)")

    print("\n" + "-" * 78)
    print("EXIT RULES - fixed now, before any outcome is known")
    print("-" * 78)
    for line in policy.describe():
        print(f"  * {line}")

    for p in proposed:
        c = p["contract"]
        print("\n" + "-" * 78)
        print(f"{p['variant'].upper()}  |  {p['ticker']}  |  {p['action']}  "
              f"|  score {p['composite_score']:+.2f}")
        print("-" * 78)
        print(f"  Contract : {c['expiration']}  {c['strike']:g} {c['type']}  "
              f"({c['dte']} DTE, delta {c['delta']:+.2f}, IV {c['iv_solved']:.1%})")
        print(f"  Quote    : {c['bid']:.2f} / {c['ask']:.2f}   spread {c['relative_spread']:.1%}"
              f"   OI {c['open_interest']:,}   vol {c['volume']:,}")
        print(f"  Entry est: {p['entry_fill_estimate']:.2f}  (a buyer crosses the spread)")
        if p["breakeven_move_pct"] is not None:
            print(f"  Breakeven: {p['breakeven_move_pct']:.2%} underlying move to cover costs")
        print(f"  Gate     : {p['gate_decision']}   ({', '.join(p['gate_failed']) or 'no failures'})")
        print(f"\n  WHY: {p['rationale']}")

    abstained = [p for p in picks if p["action"] == "ABSTAIN"]
    if abstained:
        print("\n" + "-" * 78)
        print(f"ABSTENTIONS ({len(abstained)}) - recorded, not discarded")
        print("-" * 78)
        for p in abstained:
            print(f"  {p['variant']:<22} {p['ticker']:<6} {p['reason']}")

    out_dir = Path(a.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"picks_{a.decision_date}_{stamp}.json"
    path.write_text(json.dumps(frozen, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"Frozen to : {path}")
    print(f"SHA-256   : {frozen['picks_sha256']}")
    print("\nCommit this file. It is the record, and unlike the data store it is not")
    print("regenerable - re-running tomorrow produces tomorrow's picks, not today's.")
    print(f"\nScore it later with:\n    python resolve_picks.py {path}")
    print("\nPaper/simulation only. Hypotheses for forward measurement, not advice.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
