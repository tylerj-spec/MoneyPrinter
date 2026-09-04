#!/usr/bin/env python3
"""
Money Printer - data fetcher. Run this on YOUR machine.

    pip install yfinance
    python fetch_data.py

Downloads free daily bars for SPY, QQQ, MSFT, normalizes them into the
four-timestamp point-in-time contract, and writes immutable vintage files.

Costs nothing. No API key. No account.

Also snapshots today's option chain if --chains is passed. Yahoo has no
HISTORICAL chains, so daily snapshots are the only way to accumulate genuinely
point-in-time options data. Six months of these is six months you cannot buy
retroactively - vendor "historical" files are reconstructions, not observations.

Safe to re-run. Each run writes a new timestamped vintage and never overwrites
a previous one.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from adapters.yahoo_daily import (normalize_bars, fetch_daily_bars_yfinance,  # noqa: E402
                                  check_split_adjustment)

UNIVERSE = ["SPY", "QQQ", "MSFT"]          # approved first slice (INDEX_PLUS_ONE)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_store")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not serializable: {type(o)}")


def fetch_bars(start: str, end: str, tickers: list[str]) -> int:
    os.makedirs(os.path.join(DATA_DIR, "bars"), exist_ok=True)
    vintage = _ts()
    total = 0
    for t in tickers:
        print(f"  {t} ... ", end="", flush=True)
        try:
            raw = fetch_daily_bars_yfinance(t, start, end)
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            continue
        if not raw:
            print("no data returned")
            continue

        norm = normalize_bars(raw, t)
        ok = sum(1 for r in norm if r["status"] == "OK")
        unknown = sum(1 for r in norm if r["status"] == "UNKNOWN")

        # The split-adjustment guard. daily_total_return() has no split term and
        # is correct only while Yahoo's Close stays split-adjusted; this is where
        # that assumption gets checked rather than assumed.
        checks = check_split_adjustment(raw)
        broken = [c for c in checks if c.failed]

        path = os.path.join(DATA_DIR, "bars", f"{t}_{start}_{end}__v{vintage}.json")
        with open(path, "w") as f:
            json.dump({
                "ticker": t, "start": start, "end": end,
                "vintage_id": vintage,
                "ingested_time": datetime.now(timezone.utc).isoformat(),
                "source": "yahoo_finance_via_yfinance",
                "row_count": len(norm),
                "usable_returns": ok,
                "unknown_rows": unknown,
                "split_checks": [c.__dict__ for c in checks],
                "rows": norm,
            }, f, indent=2, default=_iso)

        print(f"{len(norm)} bars, {ok} usable returns, {unknown} UNKNOWN -> {os.path.basename(path)}")
        if broken:
            print(f"    *** SPLIT ADJUSTMENT CHECK FAILED on {len(broken)} split(s) for {t}.")
            for c in broken:
                print(f"        {c.date}: {c.detail}")
            print(f"        Those returns are marked SPLIT_UNADJUSTED and excluded.")
            print(f"        This means Yahoo's Close may no longer be split-adjusted, which")
            print(f"        would make daily_total_return() wrong across EVERY split. Verify")
            print(f"        before trusting any history built from this fetch.")
        elif any(c.verdict == "ADJUSTED" for c in checks):
            n = sum(1 for c in checks if c.verdict == "ADJUSTED")
            print(f"    split adjustment verified against {n} split(s)")
        total += len(norm)
    return total


def snapshot_chains(tickers: list[str]) -> int:
    """Point-in-time option chain snapshot. THIS is how you build options history for free."""
    import yfinance as yf
    os.makedirs(os.path.join(DATA_DIR, "chains"), exist_ok=True)
    snap_time = datetime.now(timezone.utc)
    vintage = _ts()
    total = 0
    for t in tickers:
        print(f"  {t} chain ... ", end="", flush=True)
        try:
            tk = yf.Ticker(t)
            expiries = list(tk.options or [])[:6]      # nearest 6 expiries
            blocks = []
            for exp in expiries:
                ch = tk.option_chain(exp)
                for side, df in (("CALL", ch.calls), ("PUT", ch.puts)):
                    for _, r in df.iterrows():
                        bid, ask = float(r.get("bid", 0) or 0), float(r.get("ask", 0) or 0)
                        usable = bid > 0 and ask > 0 and ask >= bid
                        blocks.append({
                            "type": side, "expiration": exp,
                            "strike": float(r.get("strike", 0) or 0),
                            "bid": bid if usable else None,
                            "ask": ask if usable else None,
                            "mid": round((bid + ask) / 2, 4) if usable else None,
                            "volume": int(r.get("volume") or 0),
                            "open_interest": int(r.get("openInterest") or 0),
                            "implied_volatility": float(r.get("impliedVolatility") or 0) or None,
                            "status": "OK" if usable else "UNKNOWN",
                        })
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            continue

        ok = sum(1 for b in blocks if b["status"] == "OK")
        path = os.path.join(DATA_DIR, "chains", f"{t}__v{vintage}.json")
        with open(path, "w") as f:
            json.dump({
                "underlying": t,
                "snapshot_time_utc": snap_time.isoformat(),
                "available_time": snap_time.isoformat(),   # observed now == available now
                "vintage_id": vintage,
                "source": "yahoo_finance_option_chain",
                "expiries": expiries,
                "contract_count": len(blocks),
                "usable_quotes": ok,
                "note": ("Observed snapshot, not a vendor reconstruction. "
                         "available_time is the true observation moment."),
                "contracts": blocks,
            }, f, indent=2)
        print(f"{len(blocks)} contracts, {ok} usable -> {os.path.basename(path)}")
        total += len(blocks)
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--tickers", default=",".join(UNIVERSE))
    ap.add_argument("--chains", action="store_true",
                    help="also snapshot today's option chains (run daily to accumulate history)")
    a = ap.parse_args()
    tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]

    try:
        import yfinance  # noqa: F401
    except ImportError:
        print("yfinance not installed. Run:  pip install yfinance")
        return 1

    print("=" * 70)
    print(f"MONEY PRINTER - free data fetch   {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)
    print(f"\nDaily bars  {a.start} -> {a.end}   {tickers}")
    n = fetch_bars(a.start, a.end, tickers)

    c = 0
    if a.chains:
        print("\nOption chain snapshots (point-in-time, observed now):")
        c = snapshot_chains(tickers)

    print("\n" + "=" * 70)
    print(f"{n} bars written" + (f", {c} contracts snapshotted" if a.chains else ""))
    print(f"Stored under: {DATA_DIR}")
    print("\nNothing was interpolated, carried forward, or estimated.")
    print("Gaps are marked UNKNOWN and break the return chain rather than bridging it.")
    if not a.chains:
        print("\nTip: re-run daily with --chains to accumulate point-in-time option")
        print("history. Yahoo has no historical chains; snapshots are the only free way.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
