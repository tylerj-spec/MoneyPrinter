#!/usr/bin/env python3
"""Run an isolated offline smoke workflow, with synthetic data and no API calls."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from app_paths import get_paths

ROOT = Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, help="new folder outside the code checkout")
    a = ap.parse_args(argv)
    target = a.out or get_paths().root / "validation" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    target = get_paths(target).root
    target.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env["MONEYPRINTER_HOME"] = str(target)
    env["PYTHONIOENCODING"] = "utf-8"
    for name in ("MASSIVE_API_KEY", "FRED_API_KEY", "SEC_USER_AGENT", "TRADIER_API_KEY",
                 "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
        env.pop(name, None)
    commands = [("replay", ["replay_options.py", "--demo"]),
                ("model", ["refine_model.py", "--demo"]),
                ("paper_init", ["paper_trading.py", "init", "--cash", "1000"]),
                ("paper_status", ["paper_trading.py", "status"]),
                ("archive_status", ["collect_data.py", "status"]),
                ("feedback", ["feedback_bundle.py"])]
    results = []
    for name, args in commands:
        try:
            run = subprocess.run([sys.executable, "-X", "utf8", *args], cwd=ROOT, env=env,
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
            (target / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            code = run.returncode
        except subprocess.TimeoutExpired:
            (target / (name + ".log")).write_text("OFFLINE COMMAND TIMED OUT\n", encoding="utf-8")
            code = 124
        results.append({"step": name, "exit_code": code})
        print(f"{name}: {'PASS' if code == 0 else 'FAIL'}")
    summary = {"schema": "moneyprinter.smoke.v1", "synthetic_only": True,
               "network_calls": 0, "active_trading_data_changed": False, "steps": results,
               "success": all(r["exit_code"] == 0 for r in results)}
    (target / "smoke_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Offline validation outputs: " + str(target))
    print("Synthetic results verify plumbing, not strategy profitability. No orders or API calls.")
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
