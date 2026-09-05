#!/usr/bin/env python3
"""
Backtest the signal layer against the label contract, with a noise floor.

    python backtest.py                       # every ticker in the store
    python backtest.py --tickers SPY,MSFT,NVDA
    python backtest.py --train 120 --test 20 --permutations 500

Writes backtests/backtest_<timestamp>.json and prints the result. The dashboard
(`python dashboard.py`) renders whatever is newest in that folder.

WHAT THIS TESTS
Whether a weighted combination of the components in strategy/components.py
predicts the sign of 5-trading-day forward excess return versus SPY, OUT OF
SAMPLE, better than the same procedure scores on permuted labels.

WHAT THIS IS NOT
Not an options backtest. Yahoo serves only CURRENT option chains, so no
historical chain exists to price a contract against - any historical options
equity curve built from this data would be fabricated. The signal layer is
tested here; the options layer is tested forward, one day at a time, by
generate_picks.py and resolve_picks.py.

If the underlying forecast has no edge, no options overlay rescues it. So this
is the measurement that comes first, and a NO_EDGE verdict here is a real
result - arguably the most useful one, because it is the one that stops you
spending money on option data.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import is_dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MP_V01_DIR = HERE / "claude" / "app" / "mp_v01"
DEFAULT_DATA_DIR = MP_V01_DIR / "data_store"
DEFAULT_OUT_DIR = HERE / "backtests"

sys.path.insert(0, str(MP_V01_DIR / "src"))

from backtest.evaluate import EvalReport            # noqa: E402
from backtest.signal_study import (                 # noqa: E402
    ICResult, build_observations, run_study,
)
from backtest.walkforward import TradingCalendar    # noqa: E402
from strategy import components                     # noqa: E402
from strategy.variants import BY_NAME, VARIANTS     # noqa: E402

import excel_report as ex                           # noqa: E402

# The components a study needs present on every observation. Deliberately the
# full set: dropping one because it is often None would quietly change which
# bars the study runs on, per variant, and make the variants incomparable.
REQUIRED = ("momentum_20d", "momentum_60d", "trend_50d", "low_volatility", "reversion")


def _plain(obj):
    """JSON-safe. Dataclasses become dicts; dates become ISO strings.

    EvalReport and ICResult get explicit treatment because every number worth
    reading on them - accuracy, z, the verdict, mean IC - is a PROPERTY, and
    dataclasses.asdict() serialises fields only. Left to the generic path they
    would round-trip as a bag of raw counts with the conclusions silently
    missing, which the dashboard would then render as blanks.
    """
    if isinstance(obj, EvalReport):
        return {
            "strategy_name": obj.strategy_name,
            "n_total": obj.n_total,
            "accuracy": obj.accuracy,
            "majority_class_rate": obj.majority_class_rate,
            "permutation_mean": obj.permutation_mean,
            "permutation_std": obj.permutation_std,
            "permutation_p_value": obj.permutation_p_value,
            "z_vs_noise": obj.z_vs_noise,
            "fold_accuracy_spread": obj.fold_accuracy_spread,
            "n_permutations": obj.n_permutations,
            "block_size": obj.block_size,
            "refit_under_permutation": obj.refit_under_permutation,
            "verdict": obj.verdict(),
            "folds": [_plain(f) for f in obj.folds],
        }
    if isinstance(obj, ICResult):
        return {"component": obj.component, "mean": obj.mean, "stdev": obj.stdev,
                "hit_rate": obj.hit_rate, "t_stat": obj.t_stat,
                "median_universe": obj.median_universe,
                "universe_is_too_small": obj.universe_is_too_small,
                "daily_readings": obj.daily_readings,
                "per_fold": list(obj.per_fold)}
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--tickers", default=None, help="comma-separated subset")
    ap.add_argument("--variants", default=None,
                    help=f"comma-separated subset of: {', '.join(BY_NAME)}")
    ap.add_argument("--train", type=int, default=180, help="training SESSIONS per fold")
    ap.add_argument("--test", type=int, default=30, help="test SESSIONS per fold")
    ap.add_argument("--embargo", type=int, default=2, help="embargo SESSIONS after each test")
    ap.add_argument("--permutations", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)

    chosen = VARIANTS
    if a.variants:
        names = [v.strip() for v in a.variants.split(",") if v.strip()]
        unknown = [n for n in names if n not in BY_NAME]
        if unknown:
            ap.error(f"unknown variant(s): {', '.join(unknown)}. "
                     f"Available: {', '.join(BY_NAME)}")
        chosen = tuple(BY_NAME[n] for n in names)

    data_dir = Path(a.data_dir).expanduser().resolve()
    only = a.tickers.split(",") if a.tickers else None

    print("=" * 78)
    print("MONEY PRINTER - signal backtest with a noise floor")
    print("=" * 78)
    print("\nThis tests the SIGNAL on the underlying, not the options picks.")
    print("No historical option chains exist in this data, so an options equity")
    print("curve would be fabricated. The options layer is tested FORWARD.\n")

    data = ex.collect(data_dir, only)
    if not data["rows"]:
        print("No bars in the store. Fetch first:")
        print("    python claude/app/mp_v01/fetch_data.py --tickers SPY,QQQ,MSFT,NVDA")
        return 1
    if not data["benchmark_present"]:
        print(f"{ex.BENCHMARK} is not in the store, so excess return is undefined")
        print("and every label is unusable. Re-fetch including the benchmark:")
        print(f"    python claude/app/mp_v01/fetch_data.py --tickers {ex.BENCHMARK},QQQ,MSFT")
        return 1

    obs = build_observations(data["rows"], data["labels"], components.compute,
                             required=REQUIRED, exclude=(ex.BENCHMARK,))
    sessions = sorted({r["date"] for rs in data["rows"].values() for r in rs if r.get("date")})
    if not sessions:
        print("No dated bars in the store.")
        return 1
    calendar = TradingCalendar.from_dates(sessions)

    print(f"Instruments   : {', '.join(sorted(data['rows']))}"
          f"   (benchmark {ex.BENCHMARK} excluded from the study)")
    print(f"Sessions      : {len(calendar)}  {calendar.first} .. {calendar.last}")
    print(f"Observations  : {len(obs)}  (complete components AND a resolved label)")

    try:
        study = run_study(obs, calendar, chosen, train_sessions=a.train,
                          test_sessions=a.test, embargo_sessions=a.embargo,
                          n_permutations=a.permutations, seed=a.seed)
    except ValueError as e:
        print(f"\nCannot run a study on this data: {e}")
        need = a.train + 5 + a.test
        print(f"\nA fold needs {a.train} training + 5 purge + {a.test} test = {need} sessions,")
        print(f"and the store has {len(calendar)}. Fetch a longer history, or lower")
        print(f"--train / --test. Shorter folds are weaker evidence, not free evidence.")
        return 1

    splits = study["splits"]
    print(f"Folds         : {len(splits)}  "
          f"({a.train} train / 5 purge / {a.test} test sessions, {a.embargo} embargo)")
    print(f"  first: train {splits[0].train_start}..{splits[0].train_end}"
          f"  test {splits[0].test_start}..{splits[0].test_end}")
    print(f"  last : train {splits[-1].train_start}..{splits[-1].train_end}"
          f"  test {splits[-1].test_start}..{splits[-1].test_end}")

    print("\n" + "-" * 78)
    print("CROSS-SECTIONAL RANK IC PER COMPONENT - out of sample")
    print("-" * 78)
    print("On each decision date the instruments are ranked by the component and")
    print("by their forward excess return, and those rankings are correlated. The")
    print("daily figures are averaged over each test window. It answers: on any")
    print("given day, does this component pick which name will do better?\n")
    print(f"  {'component':<20} {'mean IC':>9} {'stdev':>8} {'sign held':>10} {'t':>7} {'folds':>6}")
    for r in study["rank_ic"]:
        m, sd, h, t = r.mean, r.stdev, r.hit_rate, r.t_stat
        print(f"  {r.component:<20} {_num(m, '+.4f'):>9} {_num(sd, '.4f'):>8} "
              f"{_pct(h):>10} {_num(t, '+.2f'):>7} {len(r.per_fold):>6}")
    print("\n  A mean IC whose sign does not hold across folds is not a weak edge.")
    print("  It is no edge, measured several times.")

    thin = [r for r in study["rank_ic"] if r.universe_is_too_small]
    if thin:
        n = thin[0].median_universe
        print(f"\n  *** READ THE NUMBERS ABOVE WITH THIS IN MIND: the universe is {n}")
        print(f"      instrument(s) on a typical date. A rank correlation over {n} names")
        print(f"      can only take a few distinct values, so each daily reading is")
        print(f"      almost pure noise - and averaging noise produces a stable-looking")
        print(f"      mean with a large t. Fetch 20+ tickers before treating any IC here")
        print(f"      as a finding. This is a property of the DATA, not of the code.")

    print("\n" + "-" * 78)
    print("WALK-FORWARD RESULT PER VARIANT")
    print("-" * 78)
    for vr in study["variants"]:
        print(f"\n{vr.variant.upper()}  -  {vr.description}")
        print(f"  train rows {vr.n_train}   test rows {vr.n_test}")
        for line in vr.report.render().splitlines():
            print(f"  {line}")

    out_dir = Path(a.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"backtest_{stamp}.json"
    path.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "signal_layer_walk_forward",
        "ic_definition": "cross_sectional: ranked across instruments within each decision date, then averaged over the test window",
        "not_an_options_backtest": (
            "No historical option chains exist in this data. This measures the "
            "underlying forecast only; the options layer is tested forward."),
        "data_dir": str(data_dir),
        "source_files": data["files"],
        "label_contract_version": ex.LABEL_CONTRACT_VERSION,
        "benchmark": ex.BENCHMARK,
        "required_components": list(REQUIRED),
        **_plain({k: v for k, v in study.items() if k != "splits"}),
        "splits": [_plain(s) for s in splits],
    }, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"Written to : {path}")
    print("Dashboard  : python dashboard.py     (renders the newest of these)")
    print("\nRead the VERDICT lines, not the accuracy. Accuracy above the majority")
    print("class means nothing until it also clears the noise floor.")
    print("\nPaper/simulation only. Nothing here is advice.")
    print("=" * 78)
    return 0


def _num(v, fmt: str) -> str:
    return format(v, fmt) if isinstance(v, (int, float)) else "n/a"


def _pct(v) -> str:
    return f"{v:.0%}" if isinstance(v, (int, float)) else "n/a"


if __name__ == "__main__":
    sys.exit(main())
