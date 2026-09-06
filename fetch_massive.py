#!/usr/bin/env python3
"""Pull historical option reference/bars from Massive.

Safest first live check:
    python fetch_massive.py --diagnose --tickers SPY --as-of 2025-08-01

The diagnostic uses at most five paced calls and never prints the API key.
"""
from __future__ import annotations

import argparse
import getpass
import os
import warnings
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
    with path.open("x", encoding="utf-8") as output:
        json.dump(doc, output, indent=2, default=str, allow_nan=False)
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
    elif v == "AUTH_FAILED":
        print("Authentication failed. Check the key; this is not proof of a missing subscription.")
    elif v == "RATE_LIMITED":
        print("Rate limit reached. Stop concurrent requests; do not retry automatically or upgrade based on this alone.")
    elif v == "NOT_ENTITLED":
        print("HTTP 402/403 denied access. Check permissions and plan; a valid key is not established by this alone.")
    elif v == "UNREACHABLE":
        print("No HTTP answer reached the adapter: check DNS, network, TLS, or proxy settings.")
    elif v in ("INVALID_RESPONSE", "REDIRECT_REFUSED"):
        print("Malformed data or a refused redirect. No historical capability was established.")
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
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
            "point_in_time_status": "VENDOR_AS_OF_REQUESTED_NOT_INDEPENDENTLY_VERIFIED",
            "note": "Reference metadata, not a historical bid/ask chain or proof of listing dates.",
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
            "note": "Trade aggregates, not executable bid/ask quotes; not consumed by the pick resolver.",
        })
        total_bars += len(rows)
    print(f"{total_contracts} contracts, {total_bars} bars written under {data_dir}")
    return 1 if failures or not total_contracts else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--diagnose", action="store_true", help="at most five paced reference calls; no data saved")
    mode.add_argument("--probe", action="store_true", help="legacy one-call reference smoke test")
    ap.add_argument("--prompt-key", action="store_true", help="hidden session-only key prompt; never an argv secret")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--tickers", default="SPY")
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--bars", action="store_true")
    ap.add_argument("--bars-from", default=None)
    ap.add_argument("--max-contracts", type=int, default=25)
    ap.add_argument("--max-pages", type=int, default=20)
    a = ap.parse_args(argv)
    try:
        tickers = [mv._underlying(t) for t in a.tickers.split(",")]
        if (a.diagnose or a.probe) and len(tickers) != 1:
            raise ValueError("diagnostics require exactly one ticker")
        if a.as_of:
            mv._date(a.as_of)
        if a.bars_from:
            mv._date(a.bars_from)
            if not a.as_of or a.bars_from > a.as_of:
                raise ValueError("--bars-from requires --as-of and must not be later")
        if a.max_pages < 1 or a.max_contracts < 1:
            raise ValueError("--max-pages and --max-contracts must be positive")
        if (a.diagnose or a.probe) and (a.bars or a.bars_from):
            raise ValueError("diagnostics cannot be combined with bar-download flags")
        if not (a.diagnose or a.probe or a.as_of):
            raise ValueError("--as-of is required for a fetch; use --diagnose first")
    except ValueError as exc:
        ap.error(str(exc))
    a.tickers = ",".join(tickers)
    previous_key = os.environ.get(mv.TOKEN_ENV_VAR)
    try:
        if a.prompt_key:
            # getpass normally falls back to echoing when no secure terminal
            # exists. Turn that warning into an error BEFORE fallback input.
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                secret = getpass.getpass("Massive API key (hidden, this run only): ").strip()
            if not secret:
                print("No key entered; no request sent.")
                return 1
            os.environ[mv.TOKEN_ENV_VAR] = secret
            del secret
        if a.diagnose:
            return do_diagnose(a)
        if a.probe:
            return do_probe(a)
        return do_fetch(a)
    except (getpass.GetPassWarning, EOFError):
        print("A hidden terminal prompt is unavailable. Use the masked GUI key box.")
        return 1
    finally:
        if a.prompt_key:
            if previous_key is None:
                os.environ.pop(mv.TOKEN_ENV_VAR, None)
            else:
                os.environ[mv.TOKEN_ENV_VAR] = previous_key



if __name__ == "__main__":
    sys.exit(main())
