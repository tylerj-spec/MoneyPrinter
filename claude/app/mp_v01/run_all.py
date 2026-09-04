#!/usr/bin/env python3
"""Run every test and the demo. Requires only Python 3.10+. No dependencies.

    python run_all.py
"""
import subprocess, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
steps = [
    ("Point-in-time / no-lookahead tests", ["tests/test_no_lookahead.py"]),
    ("Backtest, cost and risk-gate tests", ["tests/test_backtest_and_gates.py"]),
    ("Label contract v1.0",                 ["tests/test_label_contract.py"]),
    ("Yahoo adapter + eval harness",        ["tests/test_adapter_and_eval.py"]),
    ("Options: Black-Scholes, IV, Greeks",  ["tests/test_options_greeks.py"]),
    ("Strategy, variants, frozen picks",    ["tests/test_strategy_picks.py"]),
    ("End-to-end demo (synthetic data)",   ["demo/run_demo.py"]),
    ("Noise-floor harness validation",     ["demo/run_noise_floor.py"]),
]
fail = 0
for title, args in steps:
    r = subprocess.run([sys.executable] + [os.path.join(HERE, a) for a in args])
    if r.returncode != 0:
        print(f"\n!! FAILED: {title}")
        fail += 1
print("\n" + "="*72)
print("ALL GREEN" if not fail else f"{fail} STEP(S) FAILED")
print("="*72)
sys.exit(fail)
