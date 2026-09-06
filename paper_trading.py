#!/usr/bin/env python3
"""Inspect a local paper account or explicitly submit a simulation command."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from app_paths import get_paths
sys.path.insert(0, str(Path(__file__).resolve().parent / "claude/app/mp_v01/src"))
from paper.ledger import PaperLedger


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("init", "status", "submit", "quote", "cancel"))
    ap.add_argument("--cash", type=float, default=1000)
    ap.add_argument("--db", type=Path)
    ap.add_argument("--file", type=Path)
    ap.add_argument("--order-id")
    ap.add_argument("--at", default=None, help="explicit replay timestamp; otherwise current UTC")
    a = ap.parse_args(argv)
    at = a.at or datetime.now(timezone.utc).isoformat()
    if a.action in {"submit", "quote"} and a.file is None:
        ap.error("--file is required")
    if a.action == "cancel" and not a.order_id:
        ap.error("--order-id is required")
    try:
        with PaperLedger(a.db or get_paths().root / "paper" / "ledger.sqlite") as ledger:
            if a.action == "init":
                result = ledger.initialize(a.cash, at)
            elif a.action == "status":
                result = ledger.snapshot(at)
            elif a.action == "cancel":
                result = ledger.cancel(a.order_id, at=at)
            else:
                doc = json.loads(a.file.read_text("utf-8"))
                if a.action == "quote":
                    result = ledger.observe(doc, at=at)
                else:
                    result = ledger.submit(doc["order_id"], at=at, contract=doc["contract"],
                        side=doc["side"], quantity=doc["quantity"], limit_price=doc["limit_price"],
                        session=doc["session"], pick_id=doc["pick_id"])
        print(json.dumps(result, indent=2, allow_nan=False))
        print("LOCAL PAPER SIMULATION. A submitted order is not a filled or approved recommendation.")
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print("PAPER_REJECTED: " + str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
