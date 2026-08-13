from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from harness import test, assert_raises, run_all
from labels.contract import (build_label, log_total_return, decision_time_utc_for,
                             LabelStatus, LABEL_CONTRACT_VERSION, HORIZON_TRADING_DAYS)

FLAT = [0.0] * 5

@test
def contract_is_versioned():
    assert LABEL_CONTRACT_VERSION == "1.0.0"
    assert HORIZON_TRADING_DAYS == 5

@test
def decision_clock_is_1545_et_not_the_close():
    dt = decision_time_utc_for("2026-06-15")   # unambiguously EDT (summer)
    assert dt.hour == 19 and dt.minute == 45, dt   # 15:45 EDT == 19:45 UTC
    # The 16:00 ET close is 20:00 UTC - strictly after the decision.
    assert dt.hour < 20, "decision must precede the close it is scored against"

@test
def decision_clock_is_correct_in_standard_time_too():
    """2026-03-05 is BEFORE that year's DST start (2026-03-08), so it's EST
    (UTC-5), not EDT. A hard-coded UTC-4 offset gets this silently wrong for
    roughly half the year - this is exactly the bug a fixed offset causes."""
    dt = decision_time_utc_for("2026-03-05")
    assert dt.hour == 20 and dt.minute == 45, dt   # 15:45 EST == 20:45 UTC

@test
def decision_clock_is_correct_across_the_march_dst_transition():
    before = decision_time_utc_for("2026-03-05")   # EST, UTC-5
    after = decision_time_utc_for("2026-03-09")     # EDT, UTC-4 (DST started Mar 8)
    assert before.hour == 20, before
    assert after.hour == 19, after

@test
def decision_clock_is_correct_across_the_november_dst_transition():
    before = decision_time_utc_for("2026-10-30")    # still EDT, UTC-4
    after = decision_time_utc_for("2026-11-02")      # EST again (DST ended Nov 1), UTC-5
    assert before.hour == 19, before
    assert after.hour == 20, after

@test
def outperformance_labels_one():
    lab = build_label("MSFT", "2026-03-05", [0.01]*5, FLAT)
    assert lab.y == 1 and lab.is_usable()
    assert lab.excess_log_return > 0

@test
def underperformance_labels_zero():
    lab = build_label("MSFT", "2026-03-05", [-0.01]*5, FLAT)
    assert lab.y == 0

@test
def rising_but_lagging_the_benchmark_is_still_zero():
    """The bar is beating SPY, not merely going up."""
    lab = build_label("MSFT", "2026-03-05", [0.01]*5, [0.02]*5)
    assert lab.y == 0, "up 1%/day but SPY up 2%/day must be a negative label"

@test
def benchmark_uses_absolute_sign_not_self_excess():
    up = build_label("SPY", "2026-03-05", [0.01]*5, [0.01]*5)
    dn = build_label("SPY", "2026-03-05", [-0.01]*5, [-0.01]*5)
    assert up.y == 1 and dn.y == 0, "SPY vs itself would always be exactly 0"

@test
def log_returns_compound_correctly():
    assert abs(log_total_return([0.1, 0.1]) - math.log(1.21)) < 1e-12

@test
def unresolved_corporate_action_fails_closed():
    lab = build_label("MSFT", "2026-03-05", [0.01]*5, FLAT,
                      corporate_action_resolved=False)
    assert lab.y is None
    assert lab.status == LabelStatus.CORPORATE_ACTION_UNRESOLVED
    assert not lab.is_usable()

@test
def short_forward_window_fails_closed():
    lab = build_label("MSFT", "2026-03-05", [0.01]*3, FLAT)
    assert lab.y is None and lab.status == LabelStatus.INSUFFICIENT_FORWARD_BARS

@test
def delisting_with_dlret_compounds_into_final_bar():
    lab = build_label("XYZ", "2026-03-05", [0.0]*4 + [0.0], FLAT,
                      delisted_in_horizon=True, delisting_return=-0.9)
    assert lab.y == 0
    assert not lab.delisting_return_imputed

@test
def missing_dlret_imputes_total_loss_and_flags_it():
    lab = build_label("XYZ", "2026-03-05", [0.0]*5, FLAT,
                      delisted_in_horizon=True, delisting_return=None)
    assert lab.delisting_return_imputed is True
    assert lab.excess_log_return == float("-inf")
    assert lab.y == 0

@test
def none_in_return_series_raises_rather_than_silently_zeroing():
    assert_raises(ValueError, log_total_return, [0.01, None])

@test
def a_gap_day_inside_the_window_fails_closed_instead_of_crashing():
    """A None in the middle of an otherwise-long-enough series (e.g. one
    NO_PRIOR_CLOSE bar) must not raise out of build_label - a batch label
    builder processing thousands of instrument-days can't have one bad day
    take down the whole run. It must come back as an unresolved label."""
    lab = build_label("MSFT", "2026-03-05", [0.01, 0.01, None, 0.01, 0.01], FLAT)
    assert lab.y is None
    assert lab.status == LabelStatus.RETURN_GAP_UNRESOLVED
    assert not lab.is_usable()

@test
def a_gap_day_in_the_benchmark_series_also_fails_closed():
    lab = build_label("MSFT", "2026-03-05", [0.01]*5, [0.0, None, 0.0, 0.0, 0.0])
    assert lab.y is None
    assert lab.status == LabelStatus.RETURN_GAP_UNRESOLVED

@test
def labels_are_immutable():
    lab = build_label("MSFT", "2026-03-05", [0.01]*5, FLAT)
    try:
        lab.y = 0
    except Exception:
        return
    raise AssertionError("Label must be frozen")

if __name__ == "__main__":
    sys.exit(0 if run_all("LABEL CONTRACT v1.0") else 1)
