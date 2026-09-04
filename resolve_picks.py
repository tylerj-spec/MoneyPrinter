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
from strategy.picks import verify                          # noqa: E402
from strategy.resolve import resolve_pick, summarise       # noqa: E402

import excel_report as ex                                  # noqa: E402


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

    results = [resolve_pick(p, data["rows"].get(p["ticker"], []),
                            ex.load_chains_by_date(Path(a.data_dir).expanduser().resolve(),
                                                   p["ticker"]),
                            costs)
               for p in proposed]

    print("\n" + "-" * 78)
    print(f"{'variant':<20}{'tkr':<6}{'exit':>14}{'held':>5}{'move':>8}{'ok':>4}"
          f"{'ret':>9}{'mark':>10}")
    print("-" * 78)
    for r in results:
        if r["status"] != "RESOLVED":
            print(f"{r['variant']:<20}{r['ticker']:<6}{r['status']:>14}"
                  f"   {r.get('detail','')}")
            continue
        move = f"{r['underlying_move_pct']:+.2%}" if r["underlying_move_pct"] is not None else "—"
        ok = "—" if r["direction_correct"] is None else ("Y" if r["direction_correct"] else "n")
        print(f"{r['variant']:<20}{r['ticker']:<6}{r['exit_trigger']:>14}"
              f"{r['days_held']:>5}{move:>8}{ok:>4}"
              f"{r['exit_return_on_premium']:>+9.1%}{r['exit_mark_method']:>10}")

    resolved = [r for r in results if r["status"] == "RESOLVED"]
    if resolved:
        print("-" * 78)
        print(f"{'variant':<20}{'n':>4}{'dir ok':>9}{'mean':>9}{'best':>9}{'worst':>9}"
              f"   exit triggers")
        for row in summarise(results):
            hr = f"{row['direction_hit_rate']:.0%}" if row["direction_hit_rate"] is not None else "—"
            mean = f"{row['mean_return_on_premium']:+.1%}" if row["mean_return_on_premium"] is not None else "—"
            best = f"{row['best_return']:+.0%}" if row["best_return"] is not None else "—"
            worst = f"{row['worst_return']:+.0%}" if row["worst_return"] is not None else "—"
            print(f"{row['variant']:<20}{row['resolved']:>4}{hr:>9}{mean:>9}{best:>9}"
                  f"{worst:>9}   {row['exit_triggers']}")

        modelled = sum(1 for r in resolved if r["exit_mark_method"] == "MODELLED")
        if modelled:
            print(f"\n  NOTE: {modelled} of {len(resolved)} exit marks are MODELLED, not "
                  f"observed quotes.\n  They assume IV was unchanged since entry, which after "
                  f"a real move is\n  the assumption most likely to be wrong. Fetch daily "
                  f"with --chains to\n  accumulate the snapshots that give market marks.")

    print("\n" + "=" * 78)
    print(f"{len(resolved)} resolved observation(s). The pre-registration in README.md asks")
    print("for >= 200 non-overlapping decisions before any of this means anything.")
    print("A handful of resolved picks is a sample size of a handful.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
