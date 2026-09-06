#!/usr/bin/env python3
"""Pull historical option reference/bars from Massive.

Safest first live check:
    python fetch_massive.py --diagnose --tickers SPY --as-of 2025-08-01

The diagnostic uses at most five paced calls and never prints the API key.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app_paths import get_paths

PATHS = get_paths()
HERE = Path(__file__).resolve().parent
MP_V01_DIR = HERE / "claude" / "app" / "mp_v01"
DEFAULT_DATA_DIR = PATHS.data
sys.path.insert(0, str(MP_V01_DIR / "src"))
from adapters import massive_options as mv  # noqa: E402


def _write(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str, allow_nan=False), encoding="utf-8")
    return path


def do_diagnose(args) -> int:
    print("=" * 74)
    print("MASSIVE - fail-closed access ladder")
    print("=" * 74)
    print("Up to 5 calls, paced ~13s apart. The API key is read from the environment.")
    print("OK means a mechanically checkable filter matched. CONSISTENT means the")
    print("as_of response changed consistently with point-in-time filtering, but is not")
    print("treated as mathematical proof. UNVERIFIED means do not backfill yet.\n")
    try:
        steps = mv.diagnose_access(args.tickers.split(",")[0].strip().upper(), args.as_of)
    except mv.MissingCredential as e:
        print(e)
        return 1
    except ValueError as e:
        print(f"Invalid --as-of date: {e}")
        return 1

    first_problem = None
    for st in steps:
        v = st["verdict"]
        print(f"  [{v:<14}] {st['step']:<18} {st['asks']}")
        if st.get("params"):
            print(f"      sent      : {st['params']}")
        if "returned" in st:
            print(f"      returned  : {st['returned']} row(s)"
                  f"{'  underlyings ' + ', '.join(st['underlyings_returned']) if st.get('underlyings_returned') else ''}")
        if st.get("expirations_returned"):
            print(f"      expiries  : {', '.join(st['expirations_returned'])}")
        if st.get("detail"):
            print(f"      -> {st['detail']}")
        if v not in ("OK", "CONSISTENT") and first_problem is None:
            first_problem = st

    print("\n" + "-" * 74)
    final = steps[-1] if steps else None
    if final and final["step"] == "point in time" and final["verdict"] == "CONSISTENT" \
            and first_problem is None:
        print("DIAGNOSTIC: POINT_IN_TIME_CONSISTENT")
        print("All directly checkable filters passed and adding as_of changed the")
        print("deterministic sample. Reference history is plausible enough for a small")
        print("canary fetch, but historical price/quote entitlement is still separate.")
        return 0

    if first_problem is None:
        first_problem = final
    if first_problem is None:
        print("DIAGNOSTIC: NO_RESPONSE")
        return 1

    v = first_problem["verdict"]
    print(f"DIAGNOSTIC: {v} at {first_problem['step']}")
    if v == "IGNORED":
        print("The service returned rows that contradict an explicit filter. Do not store")
        print("or backtest this response; silent scope errors create look-ahead/survivorship bias.")
    elif v == "EMPTY":
        print("The request was accepted but returned no rows. This can be entitlement, date")
        print("coverage, or simply no matching contracts; it is not proof of historical access.")
    elif v == "UNVERIFIED":
        print("Nothing contradicted the request, but this sample did not demonstrate the")
        print("capability. Treat history as unavailable until a stronger canary verifies it.")
    elif v == "NOT_ENTITLED":
        print("The service refused this data for the key/plan. Do not attempt a backfill.")
    elif v == "UNREACHABLE":
        print("No HTTP answer reached the adapter: check DNS, network, TLS, or proxy settings.")
    else:
        print("The service returned an error that the adapter could not safely classify further.")
    return 1


def do_probe(args) -> int:
    r = mv.probe(args.tickers.split(",")[0].strip().upper(), args.as_of)
    print(f"Endpoint : {r['endpoint']}")
    print(f"Asked    : {r['underlying']} contracts as of {r['as_of']}")
    if not r.get("ok"):
        print(f"RESULT   : FAILED ({r.get('reason')})")
        print(r.get("detail", ""))
        return 1
    print(f"RESULT   : OK ({r.get('status')!r}); reference rows={r['returned']}")
    print("This legacy smoke test does NOT establish point-in-time history. Use --diagnose.")
    return 0


def do_fetch(args) -> int:
    data_dir = Path(args.data_dir).expanduser().resolve()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total_contracts = total_bars = failures = 0
    for t in tickers:
        print(f"{t} ... ", end="", flush=True)
        try:
            contracts = mv.list_contracts_as_of(t, args.as_of, max_pages=args.max_pages)
        except mv.MissingCredential as e:
            print("no key"); print(e); return 1
        except mv.MassiveError as e:
            print(f"FAILED: {e}"); failures += 1; continue
        usable = [c for c in contracts if c["status"] == "OK"]
        print(f"{len(contracts)} contracts, {len(usable)} usable")
        _write(data_dir / "massive_contracts" / f"{t}_{args.as_of}__v{stamp}.json", {
            "underlying": t, "as_of": args.as_of, "vintage_id": stamp,
            "ingested_time": now, "source": "massive_options_contracts",
            "endpoint": mv.CONTRACTS_PATH, "contract_count": len(contracts),
            "usable": len(usable), "contracts": contracts,
        })
        total_contracts += len(contracts)
        if not args.bars:
            continue
        rows = []
        for c in usable[:args.max_contracts]:
            try:
                rows.extend(mv.contract_daily_bars(c["contract_symbol"],
                                                   args.bars_from or args.as_of, args.as_of))
            except mv.MassiveError as e:
                print(f"  {c['contract_symbol']}: {e}"); failures += 1
        ok = sum(1 for r in rows if r["status"] == "OK")
        _write(data_dir / "massive_bars" / f"{t}_{args.as_of}__v{stamp}.json", {
            "underlying": t, "as_of": args.as_of, "vintage_id": stamp,
            "ingested_time": now, "source": "massive_option_aggregates",
            "endpoint": mv.AGGS_PATH, "row_count": len(rows), "usable": ok, "rows": rows,
        })
        total_bars += len(rows)
    print(f"{total_contracts} contracts, {total_bars} bars written under {data_dir}")
    return 1 if failures or not total_contracts else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--diagnose", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--tickers", default="SPY")
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--bars", action="store_true")
    ap.add_argument("--bars-from", default=None)
    ap.add_argument("--max-contracts", type=int, default=25)
    ap.add_argument("--max-pages", type=int, default=20)
    a = ap.parse_args(argv)
    if a.diagnose:
        return do_diagnose(a)
    if a.probe:
        return do_probe(a)
    if not a.as_of:
        ap.error("--as-of is required (or use --diagnose). A fetch without a point-in-time date would be survivorship-biased.")
    return do_fetch(a)


if __name__ == "__main__":
    sys.exit(main())
