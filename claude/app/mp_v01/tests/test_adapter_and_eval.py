from __future__ import annotations
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from harness import test, assert_raises, run_all
from adapters.yahoo_daily import (normalize_bars, bar_available_time, bar_event_time,
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

@test
def the_leak_guard_now_runs_inside_the_evaluation_path():
    """assert_no_future_features was defined, tested, and never called. A fold
    carrying decision times must be checked without anyone remembering to."""
    D = lambda s: datetime.fromisoformat(s + "T00:00:00+00:00")
    overlapping = Fold(0, [{}], [1], [{}], [0],
                       train_times=[D("2026-03-10")], test_times=[D("2026-03-01")])
    assert_raises(LeakageError, evaluate_walk_forward, [overlapping],
                  lambda tX, ty, eX: [1] * len(eX))
    too_close = Fold(0, [{}], [1], [{}], [0],
                     train_times=[D("2026-03-01")], test_times=[D("2026-03-03")])
    assert_raises(LeakageError, evaluate_walk_forward, [too_close],
                  lambda tX, ty, eX: [1] * len(eX))
    ok = Fold(0, [{}], [1], [{}], [0],
              train_times=[D("2026-03-01")], test_times=[D("2026-03-20")])
    evaluate_walk_forward([ok], lambda tX, ty, eX: [1] * len(eX), n_permutations=2)

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
