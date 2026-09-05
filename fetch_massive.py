#!/usr/bin/env python3
"""
Pull HISTORICAL option data from Massive (formerly Polygon.io).

    python fetch_massive.py --probe                    # start here: ONE call
    python fetch_massive.py --tickers SPY --as-of 2024-03-05
    python fetch_massive.py --tickers SPY,MSFT --as-of 2024-03-05 --bars

WHY THIS MATTERS MORE THAN THE OTHER FETCHERS
Yahoo serves only CURRENT option chains, which is why backtest.py measures the
signal layer and refuses to draw an options equity curve - the numbers for one
would have to be invented. Massive sells the history that removes that
constraint, IF this account is entitled to it.

START WITH --probe
Nothing here has been run against the live service: this repository's build
environment cannot reach api.massive.com. --probe spends a single call and
reports what came back, so an entitlement problem costs one request rather than
a whole backfill. Subscriptions are sold per asset class, so a working key that
covers stocks and not options is an ordinary outcome, not a fault.

THE KEY
Read from MASSIVE_API_KEY, the vendor client's own variable name. Set it once:

    setx MASSIVE_API_KEY "your-key"      (Windows; then open a NEW terminal)

or paste it into the app's key box, which passes it to this process without
writing it to disk. It is never logged, and the adapter scrubs it from any
error text before that text can be printed.
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

sys.path.insert(0, str(MP_V01_DIR / "src"))

from adapters import massive_options as mv          # noqa: E402


def _write(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str, allow_nan=False),
                    encoding="utf-8")
    return path


def do_probe(args) -> int:
    print("=" * 74)
    print("MASSIVE - probe. One call, to find out what this key can do.")
    print("=" * 74)
    r = mv.probe(args.tickers.split(",")[0].strip().upper(), args.as_of)
    print(f"\nEndpoint : {r['endpoint']}")
    print(f"Asked    : {r['underlying']} contracts as of {r['as_of']}")

    if not r.get("ok"):
        reason = r.get("reason")
        print(f"\nRESULT   : FAILED ({reason})")
        print(f"  {r.get('detail', '')}\n")
        if reason == "NO_KEY":
            print("Set the key and try again. Nothing was sent.")
        elif reason == "NOT_ENTITLED":
            print("The key was accepted by the service but not for THIS data.")
            print("Massive sells subscriptions per asset class - Stocks, Options,")
            print("Indices, Currencies, Futures - and they are independent. A free")
            print("Stocks plan does not include Options. Check the dashboard; if")
            print("options history is not included, this route is closed and the")
            print("forward paper record remains the only options evidence.")
        elif reason == "UNREACHABLE":
            print("The host could not be reached at all - network, DNS or a proxy.")
        return 1

    print(f"\nRESULT   : OK  (status {r.get('status')!r})")
    print(f"  contracts returned : {r['returned']}"
          f"{'  (more pages available)' if r['has_next_page'] else ''}")
    if r["returned"] == 0:
        print("\n  Zero rows is not necessarily an error: it can mean the account")
        print("  cannot see history that far back. Re-probe with a recent --as-of")
        print("  to tell 'not entitled to history' from 'no contracts that day'.")
    for c in r.get("sample", []):
        print(f"    {c['contract_symbol']}  {c['expiration']}  "
              f"{c['strike']} {c['type']}  [{c['status']}]")
    if r.get("unexpected_keys"):
        print(f"\n  Fields this adapter does not yet read: {', '.join(r['unexpected_keys'])}")
        print("  Not a failure - worth a look in case something useful was added.")

    print("\nThe `as_of` parameter is what makes this point-in-time: it returns the")
    print("contracts that EXISTED that day, not the ones that still trade now.")
    print("Without it every backfill would carry survivorship bias.")
    print("\nNext:  python fetch_massive.py --tickers SPY --as-of 2024-03-05 --bars")
    return 0


def do_fetch(args) -> int:
    data_dir = Path(args.data_dir).expanduser().resolve()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print("=" * 74)
    print(f"MASSIVE - historical option contracts as of {args.as_of}")
    print("=" * 74)
    total_contracts = total_bars = 0

    for t in tickers:
        print(f"\n  {t} ... ", end="", flush=True)
        try:
            contracts = mv.list_contracts_as_of(t, args.as_of,
                                                max_pages=args.max_pages)
        except mv.MissingCredential as e:
            print("no key"); print(f"\n{e}"); return 1
        except mv.MassiveError as e:
            print(f"FAILED: {e}")
            continue

        usable = [c for c in contracts if c["status"] == "OK"]
        print(f"{len(contracts)} contracts, {len(usable)} usable")
        _write(data_dir / "massive_contracts" / f"{t}_{args.as_of}__v{stamp}.json", {
            "underlying": t, "as_of": args.as_of, "vintage_id": stamp,
            "ingested_time": now, "source": "massive_options_contracts",
            "endpoint": mv.CONTRACTS_PATH,
            "note": ("Contracts that existed on as_of, expired ones included. "
                     "The as_of parameter is what makes this point-in-time; "
                     "without it the list is survivorship-biased."),
            "contract_count": len(contracts), "usable": len(usable),
            "contracts": contracts,
        })
        total_contracts += len(contracts)

        if not args.bars:
            continue
        picked = usable[:args.max_contracts]
        print(f"      bars for {len(picked)} of {len(usable)} contracts "
              f"(--max-contracts {args.max_contracts})")
        rows: list[dict] = []
        for c in picked:
            try:
                rows.extend(mv.contract_daily_bars(
                    c["contract_symbol"], args.bars_from or args.as_of, args.as_of))
            except mv.MassiveError as e:
                print(f"      {c['contract_symbol']}: {e}")
        ok = sum(1 for r in rows if r["status"] == "OK")
        print(f"      {len(rows)} bars, {ok} usable")
        _write(data_dir / "massive_bars" / f"{t}_{args.as_of}__v{stamp}.json", {
            "underlying": t, "as_of": args.as_of, "vintage_id": stamp,
            "ingested_time": now, "source": "massive_option_aggregates",
            "endpoint": mv.AGGS_PATH,
            "note": ("Daily bars per contract. Greeks are NOT vendor-supplied "
                     "here and are solved from these quotes by options/greeks.py, "
                     "so the volatility model is this repository's and is stated."),
            "row_count": len(rows), "usable": ok, "rows": rows,
        })
        total_bars += len(rows)

    print("\n" + "=" * 74)
    print(f"{total_contracts} contracts, {total_bars} bars written")
    print(f"Stored under: {data_dir}")
    print("\nNothing was interpolated or estimated. Rows that could not be read")
    print("are marked UNKNOWN rather than dropped or filled.")
    print("=" * 74)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--probe", action="store_true",
                    help="spend ONE call to test entitlement, then stop. Start here.")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--tickers", default="SPY")
    ap.add_argument("--as-of", default=None,
                    help="the point-in-time date, YYYY-MM-DD")
    ap.add_argument("--bars", action="store_true",
                    help="also pull daily bars per contract (many more calls)")
    ap.add_argument("--bars-from", default=None,
                    help="start date for bars; defaults to --as-of")
    ap.add_argument("--max-contracts", type=int, default=25,
                    help="cap on contracts to pull bars for, per ticker (default 25). "
                         "Each one is a call; a full chain is thousands.")
    ap.add_argument("--max-pages", type=int, default=20,
                    help="cap on pagination per ticker (default 20)")
    a = ap.parse_args(argv)

    if a.probe:
        return do_probe(a)
    if not a.as_of:
        ap.error("--as-of is required (or use --probe). A fetch without a "
                 "point-in-time date would be survivorship-biased.")
    return do_fetch(a)


if __name__ == "__main__":
    sys.exit(main())
