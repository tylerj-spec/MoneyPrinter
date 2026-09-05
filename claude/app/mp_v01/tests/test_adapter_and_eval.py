from __future__ import annotations
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from harness import test, assert_raises, run_all
from adapters.yahoo_daily import (check_split_adjustment, normalize_bars, bar_available_time, bar_event_time,
                                  daily_total_return)
from backtest.evaluate import Fold, block_permute, evaluate_walk_forward
from backtest.walkforward import LeakageError
from datetime import datetime

# ---------- adapter ----------
@test
def bar_is_not_available_at_its_own_close():
    """The single easiest lookahead bug: treating a bar as usable on its own date."""
    ev = bar_event_time("2026-03-02")
    av = bar_available_time("2026-03-02")
    assert av > ev, "a bar must not be consumable at the close it describes"
    assert (av - ev).total_seconds() >= 16 * 3600

@test
def bar_available_before_next_decision_clock():
    """It must still be usable by the NEXT day's 15:45 decision, or it is useless."""
    from labels.contract import decision_time_utc_for
    av = bar_available_time("2026-03-02")
    assert av < decision_time_utc_for("2026-03-03")

@test
def total_return_includes_dividends():
    assert abs(daily_total_return(100.0, 100.0, 1.0) - 0.01) < 1e-12
    assert abs(daily_total_return(100.0, 110.0, 0.0) - 0.10) < 1e-12

@test
def nonpositive_prior_close_rejected():
    assert_raises(ValueError, daily_total_return, 0.0, 100.0)

@test
def data_gap_breaks_the_chain_instead_of_bridging_it():
    """Bridging a gap would compute a multi-day move as a one-day return."""
    rows = [{"date": "2026-03-02", "close": 100.0},
            {"date": "2026-03-03", "close": 101.0},
            {"date": "2026-03-04", "close": None},
            {"date": "2026-03-05", "close": 103.0}]
    out = normalize_bars(rows, "SPY")
    assert out[2]["status"] == "UNKNOWN"
    assert out[3]["daily_total_return"] is None, "must NOT bridge across the gap"
    assert out[3]["status"] == "NO_PRIOR_CLOSE"

@test
def nothing_is_interpolated_or_carried_forward():
    rows = [{"date": "2026-03-02", "close": 100.0},
            {"date": "2026-03-03", "close": None},
            {"date": "2026-03-04", "close": None}]
    out = normalize_bars(rows, "SPY")
    assert all(r["daily_total_return"] is None for r in out[1:])
    assert all(r["status"] == "UNKNOWN" for r in out[1:])

# ---------- split-adjustment guard (section 3.1 of the 2026-09-02 review) ----------
# The shape of NVDA's real 10-for-1 split, effective 2024-06-10. The adjusted
# closes are the ones Yahoo actually served and are what the fetch verified by
# hand: +0.7461% on the split date. The raw variant is the same session priced
# the way an UNadjusted series would price it - the prior close ten times higher.
NVDA_ADJUSTED = [{"date": "2024-06-07", "close": 120.8887, "split": 0.0},
                 {"date": "2024-06-10", "close": 121.7907, "split": 10.0},
                 {"date": "2024-06-11", "close": 120.9100, "split": 0.0}]
NVDA_RAW = [{"date": "2024-06-07", "close": 1208.887, "split": 0.0},
            {"date": "2024-06-10", "close": 121.7907, "split": 10.0},
            {"date": "2024-06-11", "close": 120.9100, "split": 0.0}]


@test
def a_split_adjusted_series_passes_the_guard():
    """The assumption daily_total_return() rests on, checked rather than assumed."""
    checks = check_split_adjustment(NVDA_ADJUSTED)
    assert len(checks) == 1, checks
    assert checks[0].verdict == "ADJUSTED", checks[0]
    assert abs(checks[0].observed_ratio - 1.007461) < 1e-5, checks[0]
    out = normalize_bars(NVDA_ADJUSTED, "NVDA")
    assert out[1]["status"] == "OK"
    assert abs(out[1]["daily_total_return"] - 0.007461) < 1e-6, out[1]

@test
def an_unadjusted_series_is_caught_instead_of_scoring_a_fake_90_percent_crash():
    """If Yahoo ever serves raw closes, every split becomes a fabricated
    catastrophe. Before this guard nothing in the pipeline would have complained."""
    checks = check_split_adjustment(NVDA_RAW)
    assert checks[0].verdict == "UNADJUSTED", checks[0]
    assert abs(checks[0].observed_ratio - 0.1) < 0.01, checks[0]
    naive = daily_total_return(NVDA_RAW[0]["close"], NVDA_RAW[1]["close"])
    assert naive < -0.89, naive          # the fabricated crash, for the record
    out = normalize_bars(NVDA_RAW, "NVDA")
    assert out[1]["status"] == "SPLIT_UNADJUSTED", out[1]
    assert out[1]["daily_total_return"] is None, "the fake -90% must not survive"
    assert out[1]["close"] == 121.7907, "prices are still real, only the return is not"

@test
def only_the_straddling_return_is_dropped_not_the_whole_series():
    """In a raw series each regime is internally consistent, so the day after the
    split is a perfectly good observation. Dropping it would be over-correction."""
    out = normalize_bars(NVDA_RAW, "NVDA")
    assert out[2]["status"] == "OK"
    assert abs(out[2]["daily_total_return"] - (120.91 / 121.7907 - 1)) < 1e-12

@test
def a_real_crash_on_a_split_date_is_not_mistaken_for_an_unadjusted_series():
    """The reason this is a split cross-check and not a magnitude threshold. A
    -40% day is a real observation and marking it UNKNOWN would silently delete
    exactly the tail events a risk model exists to see."""
    crash = [{"date": "2024-06-07", "close": 100.0, "split": 0.0},
             {"date": "2024-06-10", "close": 60.0, "split": 10.0}]
    checks = check_split_adjustment(crash)
    assert checks[0].verdict == "ADJUSTED", checks[0]
    assert normalize_bars(crash, "X")[1]["status"] == "OK"

@test
def a_reverse_split_is_checked_in_the_same_direction():
    # 1-for-10: a raw close JUMPS tenfold where an adjusted one barely moves.
    rev = [{"date": "2024-06-07", "close": 1.00, "split": 0.0},
           {"date": "2024-06-10", "close": 10.05, "split": 0.1}]
    assert check_split_adjustment(rev)[0].verdict == "UNADJUSTED"
    ok = [{"date": "2024-06-07", "close": 10.00, "split": 0.0},
          {"date": "2024-06-10", "close": 10.05, "split": 0.1}]
    assert check_split_adjustment(ok)[0].verdict == "ADJUSTED"

@test
def a_split_too_small_to_discriminate_says_so_rather_than_guessing():
    """A 5-for-4 split's unadjusted signature is a -20% day, which a real session
    can produce. Reporting IMMATERIAL is honest; flagging it would cost false
    positives, and silently skipping it would hide what was never checked."""
    small = [{"date": "2024-06-07", "close": 100.0, "split": 0.0},
             {"date": "2024-06-10", "close": 80.0, "split": 1.25}]
    c = check_split_adjustment(small)[0]
    assert c.verdict == "IMMATERIAL", c
    assert normalize_bars(small, "X")[1]["status"] == "OK"

@test
def a_split_with_no_prior_bar_is_uncheckable_not_assumed_fine():
    first = [{"date": "2024-06-10", "close": 121.79, "split": 10.0}]
    assert check_split_adjustment(first)[0].verdict == "UNCHECKABLE"

@test
def bars_with_no_split_information_behave_exactly_as_before():
    """The guard must be inert when there is nothing to check - most fetches."""
    rows = [{"date": "2026-03-02", "close": 100.0},
            {"date": "2026-03-03", "close": 101.0}]
    assert check_split_adjustment(rows) == []
    out = normalize_bars(rows, "SPY")
    assert out[1]["status"] == "OK" and abs(out[1]["daily_total_return"] - 0.01) < 1e-12


@test
def every_bar_carries_both_timestamps():
    out = normalize_bars([{"date": "2026-03-02", "close": 100.0}], "SPY")
    assert "event_time" in out[0] and "available_time" in out[0]

@test
def nan_close_is_treated_as_missing_regardless_of_numeric_type():
    """NaN detection must not depend on isinstance(x, float) - that misses
    numpy.float32 and other numeric types that aren't Python float subclasses
    but still follow IEEE self-inequality (x != x) for NaN."""
    class FakeNumpyFloat32NaN:
        """Mimics a NaN-like numeric scalar that ISN'T a Python float subclass."""
        def __eq__(self, other): return False
        def __ne__(self, other): return True

    rows = [{"date": "2026-03-02", "close": 100.0},
            {"date": "2026-03-03", "close": FakeNumpyFloat32NaN()}]
    out = normalize_bars(rows, "SPY")
    assert out[1]["status"] == "UNKNOWN", out[1]
    assert out[1]["daily_total_return"] is None

@test
def decision_time_and_bar_available_time_stay_consistent_across_dst():
    """The no-lookahead guarantee (available before next decision) must hold
    on both sides of a DST transition, not just in the summer."""
    from labels.contract import decision_time_utc_for
    for d, next_d in (("2026-03-05", "2026-03-06"),   # both EST
                      ("2026-03-09", "2026-03-10"),    # both EDT
                      ("2026-10-30", "2026-11-02")):   # spans the Nov transition
        assert bar_available_time(d) < decision_time_utc_for(next_d), d


# ---------- evaluator ----------
def _random_folds(seed=3, n_folds=6, per_fold=100, train_per_fold=200):
    """Pure noise: features and labels are independent by construction."""
    rng = random.Random(seed)
    folds = []
    for i in range(n_folds):
        tr_X = [{"x": rng.gauss(0, 1)} for _ in range(train_per_fold)]
        tr_y = [rng.randint(0, 1) for _ in range(train_per_fold)]
        te_X = [{"x": rng.gauss(0, 1)} for _ in range(per_fold)]
        te_y = [rng.randint(0, 1) for _ in range(per_fold)]
        folds.append(Fold(i, tr_X, tr_y, te_X, te_y))
    return folds


def _sign_rule(train_X, train_y, test_X):
    """Ignores the training labels - a fixed rule, not a fitted one."""
    return [1 if d["x"] > 0 else 0 for d in test_X]


def _majority_learner(train_X, train_y, test_X):
    """Genuinely fitted: reads the training labels and nothing else."""
    ones = sum(train_y)
    call = 1 if ones * 2 >= len(train_y) else 0
    return [call] * len(test_X)


@test
def harness_reports_no_edge_on_pure_noise():
    """If this ever fails, every result the harness produces is untrustworthy."""
    rep = evaluate_walk_forward(_random_folds(), _sign_rule,
                                strategy_name="noise", n_permutations=100)
    assert "NO_EDGE" in rep.verdict() or "INCONCLUSIVE" in rep.verdict(), rep.verdict()

@test
def majority_class_baseline_never_counts_as_edge():
    rep = evaluate_walk_forward(_random_folds(), lambda tX, ty, eX: [1] * len(eX),
                                strategy_name="always-1", n_permutations=50)
    assert "NO_EDGE" in rep.verdict()

@test
def a_fitted_strategy_is_refit_on_permuted_labels():
    """The whole point of the interface change. A learner that reads train_y
    must see PERMUTED train_y inside the null, or its capacity to exploit
    label structure is missing from the noise floor."""
    seen: list[tuple[int, ...]] = []

    def spy(train_X, train_y, test_X):
        seen.append(tuple(train_y))
        return [1] * len(test_X)

    folds = _random_folds(n_folds=2, per_fold=20, train_per_fold=40)
    evaluate_walk_forward(folds, spy, n_permutations=5)
    assert len(seen) == 2 + 2 * 5, len(seen)
    # The scoring pass sees real labels; the permutations must not all match it.
    assert len(set(seen)) > 2, "training labels never changed under permutation"

@test
def a_fitted_learner_on_noise_still_reads_no_edge():
    """Positive control for the refit: a learner that latches onto the training
    base rate gets above-50% test accuracy on imbalanced noise. The null must
    absorb that, because the permutation preserves class balance and so the
    learner does exactly as well against permuted labels."""
    rng = random.Random(11)
    folds = []
    for i in range(6):
        tr_y = [1 if rng.random() < 0.62 else 0 for _ in range(200)]
        te_y = [1 if rng.random() < 0.62 else 0 for _ in range(100)]
        folds.append(Fold(i, [{}] * 200, tr_y, [{}] * 100, te_y))
    rep = evaluate_walk_forward(folds, _majority_learner,
                                strategy_name="majority-learner", n_permutations=100)
    assert "NO_EDGE" in rep.verdict(), rep.verdict()

@test
def block_permutation_is_a_permutation_not_a_resample():
    """Class balance must survive, or the null is comparing against different
    data rather than the same data reordered."""
    rng = random.Random(2)
    labels = [1, 1, 0, 1, 0, 0, 0, 1, 1, 0] * 5
    for block in (1, 3, 10, 999):
        out = block_permute(labels, block, rng)
        assert len(out) == len(labels), block
        assert sum(out) == sum(labels), block

@test
def block_permutation_preserves_autocorrelation_that_iid_shuffling_destroys():
    """The reason blocks exist. On a strongly autocorrelated label series an
    IID shuffle produces a null that is too tight, which inflates z and
    manufactures significance."""
    labels = ([1] * 10 + [0] * 10) * 15          # long runs = high autocorrelation

    def runs(seq):
        return sum(1 for a, b in zip(seq, seq[1:]) if a != b)

    rng = random.Random(4)
    iid = sum(runs(block_permute(labels, 1, rng)) for _ in range(30)) / 30
    blocked = sum(runs(block_permute(labels, 20, rng)) for _ in range(30)) / 30
    assert blocked < iid * 0.5, (blocked, iid)

@test
def block_size_must_be_at_least_one():
    assert_raises(ValueError, block_permute, [0, 1, 0], 0, random.Random(1))

@test
def perfect_foresight_is_detected_as_signal():
    """Positive control: a cheating strategy MUST be flagged, or the test is vacuous."""
    rng = random.Random(5)
    folds = []
    for i in range(6):
        tr_y = [rng.randint(0, 1) for _ in range(100)]
        te_y = [rng.randint(0, 1) for _ in range(100)]
        folds.append(Fold(i, [{"leak": y} for y in tr_y], tr_y,
                          [{"leak": y} for y in te_y], te_y))
    rep = evaluate_walk_forward(folds, lambda tX, ty, eX: [d["leak"] for d in eX],
                                strategy_name="cheating", n_permutations=100)
    assert "SIGNAL_CANDIDATE" in rep.verdict(), rep.verdict()
    assert rep.accuracy == 1.0

@test
def prediction_count_mismatch_raises():
    folds = _random_folds(n_folds=1, per_fold=10)
    assert_raises(ValueError, evaluate_walk_forward, folds, lambda tX, ty, eX: [1] * 3)

@test
def a_fold_whose_rows_and_labels_disagree_is_rejected_at_construction():
    assert_raises(ValueError, Fold, 0, [{}, {}], [1], [{}], [0])
    assert_raises(ValueError, Fold, 0, [{}], [1], [{}, {}], [0])

def _et_sessions(start: str, end: str, closed: tuple = ()) -> "TradingCalendar":
    """Fixture: weekday sessions between two dates, minus the named closures."""
    from datetime import date, timedelta
    from backtest.walkforward import TradingCalendar
    d, last = date.fromisoformat(start), date.fromisoformat(end)
    shut = {date.fromisoformat(c) for c in closed}
    days = []
    while d <= last:
        if d.weekday() < 5 and d not in shut:
            days.append(d)
        d += timedelta(days=1)
    return TradingCalendar(tuple(days))


@test
def the_leak_guard_now_runs_inside_the_evaluation_path():
    """assert_no_future_features was defined, tested, and never called. A fold
    carrying decision times must be checked without anyone remembering to."""
    # 15:45 ET, the label contract's decision clock - not UTC midnight, which
    # is the evening before in New York and would name the wrong session.
    D = lambda s: datetime.fromisoformat(s + "T15:45:00-04:00")
    cal = _et_sessions("2026-02-01", "2026-04-30")
    run = lambda folds: evaluate_walk_forward(
        folds, lambda tX, ty, eX: [1] * len(eX), n_permutations=2, sessions=cal)

    overlapping = Fold(0, [{}], [1], [{}], [0],
                       train_times=[D("2026-03-10")], test_times=[D("2026-03-02")])
    assert_raises(LeakageError, run, [overlapping])
    too_close = Fold(0, [{}], [1], [{}], [0],
                     train_times=[D("2026-03-02")], test_times=[D("2026-03-04")])
    assert_raises(LeakageError, run, [too_close])
    ok = Fold(0, [{}], [1], [{}], [0],
              train_times=[D("2026-03-02")], test_times=[D("2026-03-20")])
    run([ok])


@test
def a_fold_with_times_but_no_calendar_is_refused_rather_than_approximated():
    """The purge is measured in trading days. Without a calendar there is no way
    to count them, and the old code silently counted calendar days instead - so
    it certified gaps it could not verify. Refusing is the honest failure."""
    D = lambda s: datetime.fromisoformat(s + "T15:45:00-05:00")
    timed = Fold(0, [{}], [1], [{}], [0],
                 train_times=[D("2024-11-27")], test_times=[D("2024-12-02")])
    assert_raises(LeakageError, evaluate_walk_forward, [timed],
                  lambda tX, ty, eX: [1] * len(eX))
    # With the calendar it is checkable, and this is the Thanksgiving leak: five
    # calendar days, one session.
    cal = _et_sessions("2024-11-01", "2024-12-31", closed=("2024-11-28", "2024-12-25"))
    assert_raises(LeakageError, evaluate_walk_forward, [timed],
                  lambda tX, ty, eX: [1] * len(eX), sessions=cal)
    # Folds carrying no times are unchanged: nothing to check, nothing demanded.
    untimed = Fold(0, [{}], [1], [{}], [0])
    evaluate_walk_forward([untimed], lambda tX, ty, eX: [1] * len(eX), n_permutations=2)

@test
def permutation_p_value_is_bounded():
    rep = evaluate_walk_forward(_random_folds(), _sign_rule, n_permutations=50)
    assert 0.0 < rep.permutation_p_value <= 1.0

@test
def the_report_records_how_the_null_was_built():
    """A noise floor whose method is not recorded cannot be audited later."""
    rep = evaluate_walk_forward(_random_folds(), _sign_rule, n_permutations=20,
                                label_horizon=5)
    assert rep.block_size == 10, rep.block_size
    assert rep.refit_under_permutation is True
    assert "block=10" in rep.render() and "refit=yes" in rep.render()


# ---------- EODHD credential hygiene ----------
@test
def missing_token_raises_with_guidance_not_a_silent_default():
    import os
    from adapters.eodhd_options import _token, MissingCredential, TOKEN_ENV_VAR
    saved = os.environ.pop(TOKEN_ENV_VAR, None)
    try:
        assert_raises(MissingCredential, _token)
    finally:
        if saved is not None:
            os.environ[TOKEN_ENV_VAR] = saved

@test
def token_is_redacted_from_any_text_before_logging():
    import os
    from adapters.eodhd_options import redact, TOKEN_ENV_VAR
    os.environ[TOKEN_ENV_VAR] = "SECRET-TOKEN-VALUE"
    try:
        msg = "failed: https://eodhd.com/api/options/SPY.US?api_token=SECRET-TOKEN-VALUE&fmt=json"
        out = redact(msg)
        assert "SECRET-TOKEN-VALUE" not in out, out
        assert "REDACTED" in out
    finally:
        os.environ.pop(TOKEN_ENV_VAR, None)

@test
def unknown_query_param_names_are_also_redacted():
    from adapters.eodhd_options import redact
    assert "abc123" not in redact("url?apikey=abc123&x=1")
    assert "zzz" not in redact("url?token=zzz")

@test
def contract_without_two_sided_quote_is_unknown_not_synthesized():
    from adapters.eodhd_options import normalize_contract
    for bad in ({"bid": 0, "ask": 1.2}, {"bid": None, "ask": 1.2},
                {"bid": 1.5, "ask": 1.0}, {}):
        rec = normalize_contract(bad, "2026-03-02", "SPY")
        assert rec["status"] == "UNKNOWN", bad
        assert rec["mid"] is None, "a mid must never be synthesized from a bad quote"

@test
def good_quote_produces_mid():
    from adapters.eodhd_options import normalize_contract
    rec = normalize_contract({"bid": 1.00, "ask": 1.20}, "2026-03-02", "SPY")
    assert rec["status"] == "OK" and rec["mid"] == 1.10

@test
def option_chain_not_available_at_its_own_close():
    from adapters.eodhd_options import chain_available_time
    from labels.contract import decision_time_utc_for
    assert chain_available_time("2026-03-02") > decision_time_utc_for("2026-03-02")

if __name__ == "__main__":
    sys.exit(0 if run_all("YAHOO ADAPTER + EVALUATION HARNESS") else 1)
