#!/usr/bin/env python3
"""Run every offline test suite. No market-data API calls or credentials needed."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
STEPS = [
    ("Core pipeline (point-in-time, costs, gates)", "claude/app/mp_v01/run_all.py"),
    ("Excel export", "tests/test_excel_report.py"),
    ("Dashboard", "tests/test_dashboard.py"),
    ("GUI", "tests/test_gui.py"),
    ("Run regressions", "tests/test_run_regressions.py"),
    ("PR11 diagnostics, selection, research and themes", "tests/test_pr11.py"),
    ("Local source desktop and feedback", "tests/test_app_local.py"),
]


def main():
    failed = []
    for title, script in STEPS:
        result = subprocess.run([sys.executable, str(ROOT / script)], cwd=str(ROOT))
        if result.returncode:
            failed.append(title)
            print(f"\n!! FAILED: {title}")
    print("\n" + "=" * 72)
    print("ALL SUITES PASSED" if not failed else f"{len(failed)} SUITE(S) FAILED: " + ", ".join(failed))
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
