#!/usr/bin/env python3
"""
Tests for gui.py that do not need a display.

    python tests/test_gui.py

Widgets cannot be exercised headlessly, so this covers the parts that are plain
logic and were previously wrong: console line classification (which used to
colour the risk gate's PASS verdict green, i.e. "do not trade" rendered as good
news) and the date validation guarding the fetch button.

On a machine without tkinter installed, a stub stands in so importing gui.py
still proves the module body is sound.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "claude" / "app" / "mp_v01" / "tests"))

try:
    import tkinter  # noqa: F401
    STUBBED = False
except ImportError:
    # Minimal stand-in: gui.py only touches these names at import time.
    STUBBED = True
    tk = types.ModuleType("tkinter")
    for name in ("Tk", "StringVar", "BooleanVar", "Frame", "Label", "Entry",
                 "Listbox", "Text"):
        setattr(tk, name, type(name, (), {}))
    for name in ("LEFT", "RIGHT", "TOP", "BOTTOM", "X", "Y", "BOTH", "WORD",
                 "CHAR", "END", "NORMAL", "DISABLED", "SUNKEN", "W"):
        setattr(tk, name, name.lower())
    for sub in ("ttk", "filedialog", "messagebox", "scrolledtext"):
        mod = types.ModuleType(f"tkinter.{sub}")
        mod.__getattr__ = lambda n: type(n, (), {})  # type: ignore[attr-defined]
        setattr(tk, sub, mod)
        sys.modules[f"tkinter.{sub}"] = mod
    sys.modules["tkinter"] = tk

import gui  # noqa: E402
from harness import test, run_all  # noqa: E402


@test
def gate_pass_is_not_painted_as_a_win():
    """PASS from gates/risk.py means 'do nothing'. Green would misread it."""
    assert gui.classify("    -> PASS\n") == "normal"
    assert gui.classify("  decision: PASS (no edge after costs)\n") == "normal"


@test
def test_harness_markers_are_coloured():
    assert gui.classify("  PASS  future_records_are_invisible\n") == "success"
    assert gui.classify("  FAIL  future_records_are_invisible\n") == "error"
    assert gui.classify("ALL GREEN\n") == "success"
    assert gui.classify("!! FAILED: Label contract v1.0\n") == "error"
    assert gui.classify("2 STEP(S) FAILED\n") == "error"


@test
def a_failed_ticker_fetch_is_flagged_mid_line():
    """fetch_data.py reports per-ticker failures inline, not at line start."""
    assert gui.classify("  SPY ... FAILED: HTTPError: 404\n") == "error"
    # "failed_gates" is ordinary risk-gate output, not a run failure.
    assert gui.classify("       failed: dte_out_of_band, spread_too_wide\n") == "normal"


@test
def summary_counts_are_read_not_pattern_matched():
    assert gui.classify("  24 passed, 0 failed\n") == "success"
    assert gui.classify("  22 passed, 2 failed\n") == "error"


@test
def tracebacks_and_warnings_are_flagged():
    assert gui.classify("Traceback (most recent call last):\n") == "error"
    assert gui.classify("WARNING: SPY is not in the store\n") == "warning"
    assert gui.classify("⚠️  DEVELOPMENT ONLY\n") == "warning"


@test
def echoed_commands_and_exit_lines_are_muted():
    assert gui.classify("$ /usr/bin/python fetch_data.py\n") == "command"
    assert gui.classify("<process exited 0>\n") == "info"


@test
def ordinary_output_stays_plain():
    assert gui.classify("  SPY ... 1508 bars, 1507 usable returns\n") == "normal"
    assert gui.classify("\n") == "normal"


@test
def date_validation_rejects_what_fetch_data_cannot_parse():
    ok = gui.MoneyPrinterGUI._valid_date
    assert ok("2019-01-01") and ok("2026-12-31")
    # Unpadded is accepted on purpose: strptime takes it, yfinance takes it, and
    # bar_available_time() int()s the parts. Rejecting it would be a false alarm.
    assert ok("2019-1-1")
    for bad in ("01/01/2019", "yesterday", "", "2019-13-01", "2019-02-30"):
        assert not ok(bad), bad


@test
def the_gui_points_at_scripts_that_actually_exist():
    for path in (gui.FETCH_SCRIPT, gui.EXPORT_SCRIPT, gui.MIE_SCRIPT,
                 gui.TEST_SCRIPT, gui.MP_V01_DIR / "run_all.py"):
        assert path.exists(), f"gui.py references a missing script: {path}"


if __name__ == "__main__":
    if STUBBED:
        print("  (tkinter not installed here; imported gui.py against a stub)")
    sys.exit(0 if run_all("GUI (headless)") else 1)
