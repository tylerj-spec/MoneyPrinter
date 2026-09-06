#!/usr/bin/env python3
"""Collect bounded public/provider data into an immutable local archive."""
from __future__ import annotations
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import warnings
from app_paths import get_paths
sys.path.insert(0, str(Path(__file__).resolve().parent / "claude/app/mp_v01/src"))
from localdata.providers import PROVIDERS, collect, DataError, Transport
from localdata.archive import inventory, import_manual


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=[*PROVIDERS, "public", "status", "import"], nargs="?", default="status")
    parser.add_argument("--scope", help="SEC numeric CIK, FRED/BLS series, or provider symbol")
    parser.add_argument("--vintage", help="FRED/ALFRED realtime date, YYYY-MM-DD")
    parser.add_argument("--file", type=Path, help="manual JSON import")
    parser.add_argument("--prompt-keys", action="store_true", help="hidden, session-only prompt for selected provider")
    parser.add_argument("--production", action="store_true", help="Tradier brokerage data; default is delayed sandbox")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    root = args.root or (get_paths().root / "external")
    if args.provider == "status":
        print(json.dumps(inventory(root), indent=2))
        return 0
    if args.provider == "import":
        if not args.file:
            parser.error("--file is required for import")
        try:
            path = import_manual(root, args.file)
            print(f"Imported unverified manual context: {path}")
            return 0
        except (ValueError, OSError, KeyError, TypeError):
            print("IMPORT_REJECTED: invalid schema, unsafe fields or unreadable file")
            return 1
    providers = ("bls_calendar", "fed", "bls") if args.provider == "public" else (args.provider,)
    env = dict(os.environ)
    failures = 0
    try:
        if args.prompt_keys:
            for provider in providers:
                for name in PROVIDERS[provider]["credentials"]:
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", getpass.GetPassWarning)
                        env[name] = getpass.getpass(f"{name} (hidden, this run only): ").strip()
        transport = Transport()
        for provider in providers:
            try:
                path = collect(root, provider, scope=args.scope, vintage=args.vintage,
                               production=args.production, env=env, transport=transport)
                print(f"SAVED {provider}: {path}")
            except DataError as exc:
                failures += 1
                print(f"FAILED {provider}: {exc}")
            except (ValueError, OSError):
                failures += 1
                print(f"FAILED {provider}: invalid input or local storage unavailable; no invalid response saved")
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("Secure prompt unavailable or cancelled; no echoed fallback")
        return 1
    finally:
        env.clear()
    print("Archives are context only. No weights changed; no orders were submitted.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
