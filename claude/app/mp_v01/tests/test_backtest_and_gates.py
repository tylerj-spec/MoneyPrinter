from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime, timezone, timedelta

from harness import test, assert_raises, run_all
from backtest.walkforward import make_splits, Split, LeakageError, assert_no_future_features
from backtest.costs import CostModel
from gates.risk import evaluate, Decision, RiskLimits

D = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ---------- walk-forward ----------
@test
def splits_are_chronological_and_non_overlapping():
    sp = make_splits(D("2024-01-01"), D("2026-01-01"))
    assert len(sp) > 1
    for a, b in zip(sp, sp[1:]):
        assert a.test_start < b.test_start, "splits must roll forward"
    for s in sp:
        assert s.train_end < s.test_start

@test
def purge_gap_prevents_label_horizon_bleed():
    """train_end + 5d label horizon must not reach into the test window."""
    bad = Split(0, D("2024-01-01"), D("2024-06-01"), D("2024-06-02"), D("2024-07-01"))
    assert_raises(LeakageError, bad.validate, 5)   # only 1 day gap, need 5
    ok = Split(0, D("2024-01-01"), D("2024-06-01"), D("2024-06-06"), D("2024-07-01"))
    ok.validate(5)

@test
def overlapping_train_test_rejected():
    bad = Split(0, D("2024-01-01"), D("2024-07-01"), D("2024-06-01"), D("2024-08-01"))
    assert_raises(LeakageError, bad.validate, 0)

@test
def future_features_rejected():
    dt = D("2026-03-01")
    assert_no_future_features([D("2026-02-01"), dt], dt)
    assert_raises(LeakageError, assert_no_future_features,
                  [D("2026-03-02")], dt)

@test
def too_short_range_raises_rather_than_silently_returning_nothing():
    assert_raises(ValueError, make_splits, D("2026-01-01"), D("2026-02-01"))


# ---------- costs ----------
@test
def option_buy_pays_up_and_sell_receives_less():
    c = CostModel(spread_capture=1.0)
    assert c.option_fill_price(1.00, 1.20, "BUY") == 1.20
    assert c.option_fill_price(1.00, 1.20, "SELL") == 1.00

@test
def half_spread_capture_is_midpoint_offset():
    c = CostModel(spread_capture=0.5)
    assert c.option_fill_price(1.00, 1.20, "BUY") == 1.15

@test
def round_trip_cost_is_material_on_wide_spreads():
    c = CostModel(spread_capture=1.0)
    cost = c.option_round_trip_cost(1.00, 1.20, contracts=5)
    # 0.20 spread * 100 * 5 = 100.00, plus 2*5*0.80 = 8.00
    assert abs(cost - 108.0) < 0.01, cost

@test
def stale_and_wide_quotes_are_rejected():
    c = CostModel()
    assert c.quote_is_tradeable(1.00, 1.05, 10)[0]
    assert not c.quote_is_tradeable(1.00, 1.05, 300)[0]     # stale
    assert not c.quote_is_tradeable(1.00, 1.50, 10)[0]      # 40% spread
    assert not c.quote_is_tradeable(0.0, 1.0, 1)[0]         # no bid
    assert not c.quote_is_tradeable(1.20, 1.00, 1)[0]       # crossed


# ---------- gates ----------
def _good():
    return dict(independent_events=3, evidence_confidence=0.75, dte=35,
                relative_spread=0.04, open_interest=2000, daily_volume=300,
                defined_risk=True, expected_edge_after_costs=0.03,
                position_pct=0.015, portfolio_heat_pct=0.04, open_positions=2)

@test
def clean_candidate_reaches_paper_trade_never_live():
    r = evaluate(_good())
    assert r.decision == Decision.PAPER_TRADE_CANDIDATE
    assert r.decision.value != "LIVE"

@test
def no_live_decision_exists_anywhere_in_the_enum():
    vals = {d.value for d in Decision}
    assert vals == {"PASS", "WATCH", "PAPER_TRADE_CANDIDATE"}, vals

@test
def negative_edge_after_costs_is_hard_fail():
    c = _good(); c["expected_edge_after_costs"] = -0.001
    assert evaluate(c).decision == Decision.PASS

@test
def lookahead_violation_is_hard_fail():
    c = _good(); c["cutoff_violations"] = ["evidence dated after decision"]
    r = evaluate(c)
    assert r.decision == Decision.PASS and "cutoff_violation" in r.failed_gates

@test
def syndication_collapse_can_starve_evidence_gate():
    c = _good(); c["independent_events"] = 1     # 9 articles, 1 real event
    r = evaluate(c)
    assert r.decision == Decision.WATCH
    assert "insufficient_independent_evidence" in r.failed_gates

@test
def missing_data_fails_closed_not_open():
    c = _good(); del c["expected_edge_after_costs"]
    r = evaluate(c)
    assert r.decision == Decision.PASS, "unknown input must never pass silently"
    assert any(f.startswith("missing:") for f in r.failed_gates)

@test
def oversized_position_is_hard_fail():
    c = _good(); c["position_pct"] = 0.25
    assert evaluate(c).decision == Decision.PASS

@test
def undefined_risk_structure_blocked():
    c = _good(); c["defined_risk"] = False
    assert evaluate(c).decision == Decision.PASS

@test
def gates_are_deterministic():
    c = _good()
    assert {evaluate(c).decision for _ in range(50)} == {Decision.PAPER_TRADE_CANDIDATE}

@test
def confidence_cannot_override_a_hard_gate():
    """The whole point: a 99%-confident model still cannot buy negative edge."""
    c = _good()
    c["evidence_confidence"] = 0.99
    c["expected_edge_after_costs"] = -0.05
    assert evaluate(c).decision == Decision.PASS

@test
def exact_zero_edge_is_not_good_enough():
    """min_edge_after_costs=0.0 means edge must be strictly > 0, not >= 0."""
    c = _good(); c["expected_edge_after_costs"] = 0.0
    r = evaluate(c)
    assert r.decision == Decision.PASS
    assert "no_edge_after_costs" in r.failed_gates

@test
def nan_edge_does_not_silently_pass():
    """NaN comparisons are always False - an unguarded NaN edge would slide
    past `edge <= 0` and reach PAPER_TRADE_CANDIDATE. Must fail closed instead."""
    c = _good(); c["expected_edge_after_costs"] = float("nan")
    r = evaluate(c)
    assert r.decision == Decision.PASS
    assert "invalid_numeric:expected_edge_after_costs" in r.failed_gates

@test
def infinite_position_size_does_not_silently_pass():
    c = _good(); c["position_pct"] = float("inf")
    r = evaluate(c)
    assert r.decision == Decision.PASS
    assert "invalid_numeric:position_pct" in r.failed_gates

@test
def nan_confidence_does_not_silently_pass():
    c = _good(); c["evidence_confidence"] = float("nan")
    r = evaluate(c)
    assert r.decision == Decision.PASS
    assert "invalid_numeric:evidence_confidence" in r.failed_gates

@test
def nan_portfolio_heat_does_not_silently_pass():
    c = _good(); c["portfolio_heat_pct"] = float("nan")
    r = evaluate(c)
    assert r.decision == Decision.PASS
    assert "invalid_numeric:portfolio_heat_pct" in r.failed_gates


if __name__ == "__main__":
    sys.exit(0 if run_all("BACKTEST / COSTS / RISK GATES") else 1)
