#!/usr/bin/env python3
"""Run every test in the repository.

    python run_tests.py

The core pipeline suite needs nothing but the standard library. The Excel and
GUI suites degrade rather than fail on a machine without openpyxl or tkinter:
they skip the parts that genuinely need those and still check the logic.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ("Core pipeline (point-in-time, costs, gates)", "claude/app/mp_v01/run_all.py"),
    ("Excel export", "tests/test_excel_report.py"),
    ("Dashboard (offline HTML)", "tests/test_dashboard.py"),
    ("GUI (headless)", "tests/test_gui.py"),
]

failed = []
for title, script in STEPS:
    if subprocess.run([sys.executable, os.path.join(HERE, script)]).returncode != 0:
        print(f"\n!! FAILED: {title}")
        failed.append(title)

print("\n" + "=" * 72)
print("ALL GREEN" if not failed else f"{len(failed)} SUITE(S) FAILED: {', '.join(failed)}")
print("=" * 72)
sys.exit(len(failed))
