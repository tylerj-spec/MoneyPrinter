from __future__ import annotations
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from harness import test, assert_raises, run_all
from adapters.yahoo_daily import (normalize_bars, bar_available_time, bar_event_time,
                                  daily_total_return)
from backtest.evaluate import evaluate_walk_forward

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


# ---------- evaluator ----------
def _random_folds(seed=3, n_folds=6, per_fold=100):
    rng = random.Random(seed)
    folds = []
    for _ in range(n_folds):
        feats = [{"x": rng.gauss(0, 1)} for _ in range(per_fold)]
        labels = [rng.randint(0, 1) for _ in range(per_fold)]
        folds.append((feats, labels))
    return folds

@test
def harness_reports_no_edge_on_pure_noise():
    """If this ever fails, every result the harness produces is untrustworthy."""
    folds = _random_folds()
    rep = evaluate_walk_forward(folds, lambda f: [1 if d["x"] > 0 else 0 for d in f],
                                strategy_name="noise", n_permutations=100)
    assert "NO_EDGE" in rep.verdict() or "INCONCLUSIVE" in rep.verdict(), rep.verdict()

@test
def majority_class_baseline_never_counts_as_edge():
    folds = _random_folds()
    rep = evaluate_walk_forward(folds, lambda f: [1] * len(f),
                                strategy_name="always-1", n_permutations=50)
    assert "NO_EDGE" in rep.verdict()

@test
def perfect_foresight_is_detected_as_signal():
    """Positive control: a cheating strategy MUST be flagged, or the test is vacuous."""
    rng = random.Random(5)
    folds = []
    for _ in range(6):
        labels = [rng.randint(0, 1) for _ in range(100)]
        feats = [{"leak": y} for y in labels]      # label leaked into the feature
        folds.append((feats, labels))
    rep = evaluate_walk_forward(folds, lambda f: [d["leak"] for d in f],
                                strategy_name="cheating", n_permutations=100)
    assert "SIGNAL_CANDIDATE" in rep.verdict(), rep.verdict()
    assert rep.accuracy == 1.0

@test
def prediction_count_mismatch_raises():
    folds = _random_folds(n_folds=1, per_fold=10)
    assert_raises(ValueError, evaluate_walk_forward, folds, lambda f: [1] * 3)

@test
def permutation_p_value_is_bounded():
    rep = evaluate_walk_forward(_random_folds(), lambda f: [1 if d["x"] > 0 else 0 for d in f],
                                n_permutations=50)
    assert 0.0 < rep.permutation_p_value <= 1.0


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
