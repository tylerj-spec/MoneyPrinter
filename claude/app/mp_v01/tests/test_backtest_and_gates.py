from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from datetime import date, datetime, timezone, timedelta

from harness import test, assert_raises, run_all
from backtest.walkforward import (make_splits, Split, TradingCalendar,
                                  LeakageError, assert_no_future_features)
from backtest.costs import CostModel
from gates.risk import evaluate, Decision, RiskLimits

D = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
S = lambda s: date.fromisoformat(s)   # a session is a day, not an instant


# ---------- walk-forward ----------
def _weekday_sessions(start: str, end: str, closed: tuple = ()) -> TradingCalendar:
    """Fixture: every weekday between two dates, minus the named closures.

    A fixture, NOT a holiday table. `src/` deliberately has no closure list -
    see TradingCalendar's docstring - so any test that depends on a specific
    market closure names it here, where the assumption is visible in the test
    that relies on it.
    """
    from datetime import date, timedelta
    d, last = date.fromisoformat(start), date.fromisoformat(end)
    shut = {date.fromisoformat(c) for c in closed}
    days = []
    while d <= last:
        if d.weekday() < 5 and d not in shut:
            days.append(d)
        d += timedelta(days=1)
    return TradingCalendar(tuple(days))


# 2024-11-28 was Thanksgiving and the NYSE was shut; the 29th traded (early
# close, still a session). 2024-12-25 was Christmas.
THANKSGIVING = _weekday_sessions("2024-11-01", "2024-12-31",
                                 closed=("2024-11-28", "2024-12-25"))
# 2024-07-04 was Independence Day. Named so the split boundaries can be checked
# against a calendar that actually knows the market was shut.
FOUR_YEARS = _weekday_sessions("2022-01-01", "2026-01-01",
                               closed=("2024-07-04", "2024-11-28", "2024-12-25"))


@test
def splits_are_chronological_and_non_overlapping():
    sp = make_splits(FOUR_YEARS)
    assert len(sp) > 1
    for a, b in zip(sp, sp[1:]):
        assert a.test_start < b.test_start, "splits must roll forward"
    for s in sp:
        assert s.train_end < s.test_start

@test
def every_split_boundary_lands_on_a_real_session():
    """The calendar-arithmetic version ended training on Saturday 2024-06-29 and
    opened testing on Thursday 2024-07-04, a market holiday. Laying the splits
    out in session-index space makes that unrepresentable."""
    known = set(FOUR_YEARS.sessions)
    for s in make_splits(FOUR_YEARS):
        for name in ("train_start", "train_end", "test_start", "test_end"):
            day = getattr(s, name)
            assert day in known, f"split {s.index}.{name} {day} is not a session"
            assert day.weekday() < 5, f"split {s.index}.{name} {day} is a weekend"

@test
def purge_gap_is_counted_in_sessions_not_calendar_days():
    """The rewritten version of purge_gap_prevents_label_horizon_bleed.

    That test asserted a 5-CALENDAR-day gap was a sufficient purge for a
    5-TRADING-day horizon, so the guard and the test proving the guard worked
    shared one wrong assumption. Here the gap that used to pass is rejected,
    and no holiday is needed to show it - an ordinary weekend is enough.
    """
    cal = _weekday_sessions("2024-03-01", "2024-04-30")
    # Fri 2024-03-15 -> Fri 2024-03-22 is 7 calendar days, which comfortably
    # cleared the old >= 5 check. It is 4 sessions: Mar 18, 19, 20, 21.
    too_close = Split(0, S("2024-03-01"), S("2024-03-15"), S("2024-03-22"), S("2024-04-19"))
    assert (too_close.test_start - too_close.train_end).days == 7
    assert cal.sessions_strictly_between(too_close.train_end, too_close.test_start) == 4
    assert_raises(LeakageError, too_close.validate, 5, cal)
    # Mon 2024-03-25 is the sixth session after the 15th, so five whole sessions
    # sit in the gap and the label decided on the 15th resolves on the 22nd.
    ok = Split(0, S("2024-03-01"), S("2024-03-15"), S("2024-03-25"), S("2024-04-19"))
    assert cal.sessions_strictly_between(ok.train_end, ok.test_start) == 5
    ok.validate(5, cal)

@test
def thanksgiving_week_purge_that_calendar_arithmetic_called_safe():
    """The headline regression, reproduced from the 2026-09-02 review.

    train_end 2024-11-27 (Wed), test_start 2024-12-02 (Mon): exactly 5 calendar
    days, so the old guard passed it. One of those days was a session - the
    market was shut on the 28th and the weekend follows - so a label decided on
    the 27th resolves on 2024-12-05, three sessions INSIDE the test window.
    """
    leaky = Split(0, S("2024-11-01"), S("2024-11-27"), S("2024-12-02"), S("2024-12-20"))
    assert (leaky.test_start - leaky.train_end).days == 5, "the old guard's 5-day gap"
    assert THANKSGIVING.sessions_strictly_between(leaky.train_end, leaky.test_start) == 1
    assert_raises(LeakageError, leaky.validate, 5, THANKSGIVING)

    # Where the label actually resolves: five sessions past 2024-11-27.
    i = THANKSGIVING.index_of(S("2024-11-27"))
    assert THANKSGIVING[i + 5].isoformat() == "2024-12-05"
    # So the earliest honest test open is the session after that, and the one
    # before it is still a leak.
    Split(0, S("2024-11-01"), S("2024-11-27"), S("2024-12-06"), S("2024-12-20")).validate(5, THANKSGIVING)
    still_leaky = Split(0, S("2024-11-01"), S("2024-11-27"), S("2024-12-05"), S("2024-12-20"))
    assert_raises(LeakageError, still_leaky.validate, 5, THANKSGIVING)

@test
def a_purge_cannot_be_certified_outside_the_calendar():
    """Sessions the calendar has never heard of must not be counted as zero and
    reported as a violation, nor silently treated as a clean gap."""
    s = Split(0, S("2019-01-02"), S("2019-06-03"), S("2019-06-14"), S("2019-07-01"))
    assert_raises(LeakageError, s.validate, 5, THANKSGIVING)

@test
def a_day_the_market_was_shut_is_not_a_session():
    assert_raises(LeakageError, THANKSGIVING.index_of, S("2024-11-28"))
    assert THANKSGIVING.index_of(S("2024-11-29")) >= 0

@test
def a_session_date_is_read_in_new_york_not_utc():
    """16:00 ET on the 27th is 21:00 UTC on the 27th, so a real bar timestamp
    round-trips. A UTC-midnight instant is genuinely the evening before in New
    York and resolves to the 27th, which is why nothing here builds a session
    out of one."""
    from backtest.walkforward import as_session_date
    assert as_session_date(datetime.fromisoformat("2024-11-28T21:00:00+00:00")) == S("2024-11-28")
    assert as_session_date(datetime.fromisoformat("2024-11-28T15:45:00-05:00")) == S("2024-11-28")
    assert as_session_date(datetime.fromisoformat("2024-11-28T00:00:00+00:00")) == S("2024-11-27")
    assert as_session_date("2024-11-28") == S("2024-11-28")

@test
def overlapping_train_test_rejected():
    bad = Split(0, S("2024-01-01"), S("2024-07-01"), S("2024-06-01"), S("2024-08-01"))
    assert_raises(LeakageError, bad.validate, 0, FOUR_YEARS)

@test
def future_features_rejected():
    dt = D("2026-03-01")
    assert_no_future_features([D("2026-02-01"), dt], dt)
    assert_raises(LeakageError, assert_no_future_features,
                  [D("2026-03-02")], dt)

@test
def too_short_range_raises_rather_than_silently_returning_nothing():
    short = _weekday_sessions("2026-01-01", "2026-02-01")
    assert_raises(ValueError, make_splits, short)


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
def a_non_numeric_field_fails_closed_instead_of_raising():
    """A candidate from JSON, a model or a spreadsheet can carry "35" for 35.
    Comparing that to a threshold raised TypeError, and an exception is not a
    decision - the caller then crashes or catches broadly, and a broad catch
    around a risk gate is how PASS quietly becomes "skipped"."""
    for field, bad in (("dte", "35"), ("evidence_confidence", "0.8"),
                       ("open_interest", None if False else "2500"),
                       ("position_pct", "0.015")):
        c = _good()
        c[field] = bad
        r = evaluate(c)
        assert r.decision is Decision.PASS, (field, r.decision)
        assert f"invalid_type:{field}" in r.failed_gates, (field, r.failed_gates)

@test
def booleans_are_not_accepted_as_numbers():
    """bool subclasses int, so True would slide through a naive isinstance
    check and compare as 1 against every threshold."""
    c = _good(); c["dte"] = True
    r = evaluate(c)
    assert r.decision is Decision.PASS
    assert "invalid_type:dte" in r.failed_gates, r.failed_gates

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
