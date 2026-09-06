#!/usr/bin/env python3
"""Replay a local observed-quote dataset; --demo uses explicitly synthetic data."""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from app_paths import get_paths
sys.path.insert(0, str(Path(__file__).resolve().parent / "claude/app/mp_v01/src"))
from backtest.replay import run_replay
from options.greeks import black_scholes_price


def demo_dataset():
    decision = "2026-09-04T15:00:00Z"
    session = {"open_utc": "2026-09-04T13:30:00Z", "close_utc": "2026-09-04T20:00:00Z",
               "available_utc": "2026-01-01T00:00:00Z", "source": "SYNTHETIC_SESSION_FIXTURE"}
    bars, day, close = [], date(2026, 5, 1), 100.0
    while day < date(2026, 9, 4):
        if day.weekday() < 5:
            close *= 1.002
            event = datetime(day.year, day.month, day.day, 20, tzinfo=timezone.utc)
            bars.append({"date": day.isoformat(), "close": close, "daily_total_return": .002,
                         "event_time": event.isoformat(), "available_time": (event + timedelta(hours=17)).isoformat()})
        day += timedelta(days=1)
    contracts, quotes = [], []
    for i, strike in enumerate((122, 125, 128)):
        cid = f"SYNTHETIC_CALL_{i}"
        contracts.append({"contract_id": cid, "underlying": "SPY", "type": "CALL", "strike": strike,
                          "expiration": "2026-10-16", "listed_utc": "2026-08-01T00:00:00Z", "known_utc": "2026-08-01T00:00:00Z",
                          "standard_contract": True, "premium_multiplier": 100, "deliverable_shares": 100, "spec_source": "SYNTHETIC_FIXTURE"})
        price = black_scholes_price(close, strike, 42 / 365, .04, .25, 0, "CALL")
        for stamp, bump in (("14:59:59", 0), ("15:00:02", 0), ("15:10:02", .15)):
            t = "2026-09-04T" + stamp + "Z"
            quotes.append({"contract_id": cid, "observed_utc": t, "available_utc": t,
                           "source": "SYNTHETIC_FIXTURE", "feed_type": "OPRA", "delayed": False,
                           "bid": round(price - .02 + bump, 4), "ask": round(price + .02 + bump, 4),
                           "bid_size": 5, "ask_size": 5, "size_units": "CONTRACTS", "open_interest": 2000, "volume": 100,
                           "oi_available_utc": "2026-09-04T13:00:00Z", "volume_available_utc": t})
    return {"schema": "moneyprinter.replay.v1", "provenance": "SYNTHETIC_DEMO", "source": "synthetic deterministic smoke fixture, not market data",
            "sessions": [session], "bars": {"SPY": bars}, "contracts": contracts, "quotes": quotes,
            "rate": {"value": .04, "available_utc": "2026-09-01T00:00:00Z", "source": "SYNTHETIC_ASSUMPTION"},
            "underlying_quotes": [{"contract_id": "SPY", "observed_utc": "2026-09-04T14:59:59Z", "available_utc": "2026-09-04T14:59:59Z",
                                    "bid": close - .01, "ask": close + .01, "feed_type": "CONSOLIDATED", "delayed": False, "source": "SYNTHETIC_FIXTURE"}],
            "decisions": [{"decision_utc": decision, "exit_utc": "2026-09-04T15:10:00Z", "ticker": "SPY", "variant": "momentum"}]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true")
    mode.add_argument("--dataset", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    try:
        dataset = demo_dataset() if args.demo else json.loads(args.dataset.read_text("utf-8"))
        result = run_replay(dataset)
        base = args.out or get_paths().root / ("demos" if args.demo else "replays") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        base.mkdir(parents=True, exist_ok=False)
        (base / "dataset.json").write_text(json.dumps(dataset, indent=2, allow_nan=False), encoding="utf-8")
        records = result.pop("pick_records")
        for checksum, view in result.pop("decision_input_views").items():
            (base / ("inputs_" + checksum + ".json")).write_text(json.dumps(view, indent=2, allow_nan=False), encoding="utf-8")
        from pick_review import render
        for index, record in enumerate(records):
            (base / f"picks_replay_{index}.json").write_text(json.dumps(record, indent=2, allow_nan=False), encoding="utf-8")
            (base / f"review_{index}.html").write_text(render(record, f"picks_replay_{index}.json"), encoding="utf-8")
        (base / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        (base / "review.html").write_text(render(records[0], "picks_replay_0.json") if records else "No decisions", encoding="utf-8")
        print(f"Saved replay and explanations: {base}")
        print("Provenance: " + result["dataset_provenance"])
        for out in result["outcomes"]:
            print(f"{out['selection_policy']}: {out['status']} net_pnl={out['net_pnl']}")
        print("Counterfactual research replay, not portfolio results or evidence of predictive edge.")
        return 0
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(f"REPLAY_REJECTED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
