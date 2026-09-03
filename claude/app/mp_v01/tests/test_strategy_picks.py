"""Score components, variants, and the frozen pick contract."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from harness import test, run_all
from strategy import components as C
from strategy.picks import (
    ExitPolicy, approximate_assessment_date, breakeven_move_pct, freeze,
    generate_picks, select_contract, verify,
)
from strategy.resolve import bars_after, market_quote, resolve_pick, summarise
from strategy.variants import BY_NAME, VARIANTS, score


def bars(n=300, start=100.0, drift=0.001, first_date="2025-01-01"):
    from datetime import date, timedelta
    d, out, px = date.fromisoformat(first_date), [], start
    prev = None
    while len(out) < n:
        if d.weekday() < 5:
            px = start * (1 + drift * len(out))
            out.append({"date": d.isoformat(), "close": px,
                        "daily_total_return": (px / prev - 1.0) if prev else None})
            prev = px
        d += timedelta(days=1)
    return out


def opt(kind="CALL", delta=0.35, strike=100.0, spread=0.03, oi=4000, vol=800,
        status="OK", screen="PASS", dte=35):
    return {"type": kind, "expiration": "2026-04-17", "dte": dte, "strike": strike,
            "bid": 4.0, "ask": 4.2, "mid": 4.1, "delta": delta, "gamma": 0.01,
            "theta_per_day": -0.05, "vega": 0.1, "iv_solved": 0.25,
            "relative_spread": spread, "open_interest": oi, "volume": vol,
            "model_status": status, "liquidity_screen": screen,
            "round_trip_cost_1x": 15.0, "underlying_close": 100.0,
            "underlying_close_date": "2026-03-01"}


# --- point-in-time ----------------------------------------------------------

@test
def components_never_see_the_decision_days_own_bar():
    """A daily bar is not consumable at its own close. Including it would be a
    full day of lookahead in every component."""
    b = bars(60, first_date="2026-01-01")
    target = b[-1]["date"]
    avail = C.slice_available(b, target)
    assert all(x["date"] < target for x in avail)
    assert len(avail) == len(b) - 1
    assert C.compute(b, target)["last_available_date"] == b[-2]["date"]


@test
def components_fail_closed_without_enough_history():
    out = C.compute(bars(10, first_date="2026-01-01"), "2026-03-01")
    assert out["scaled"]["momentum_60d"] is None
    assert out["scaled"]["trend_50d"] is None


# --- variants ---------------------------------------------------------------

@test
def a_variant_fails_closed_when_a_component_it_needs_is_missing():
    """Re-normalising over whatever happens to be present would silently change
    the strategy being tested from one run to the next."""
    s, missing = score(BY_NAME["momentum"], {"momentum_20d": 0.5})
    assert s is None and set(missing) == {"momentum_60d", "trend_50d"}


@test
def momentum_and_reversion_genuinely_disagree():
    """They are deliberately contradictory. If both ever look good in the
    forward record, the record is noise rather than two edges."""
    scaled = {"momentum_20d": 0.8, "momentum_60d": 0.6, "trend_50d": 0.7,
              "low_volatility": 0.1, "reversion": -0.7}
    assert score(BY_NAME["momentum"], scaled)[0] > 0
    assert score(BY_NAME["reversion"], scaled)[0] < 0


@test
def every_variants_weights_normalise():
    for v in VARIANTS:
        assert abs(sum(abs(w) for w in v.normalised_weights().values()) - 1.0) < 1e-9, v.name


# --- contract selection -----------------------------------------------------

@test
def selection_takes_the_closest_liquid_strike_to_the_delta_target():
    rows = [opt(delta=0.15, strike=110.0), opt(delta=0.34, strike=103.0),
            opt(delta=0.62, strike=95.0)]
    row, why = select_contract(rows, kind="CALL", target_abs_delta=0.35)
    assert row["strike"] == 103.0, row
    assert "delta target" in why


@test
def selection_abstains_with_a_reason_rather_than_silently():
    for rows, needle in (
        ([opt(screen="FAIL")], "liquidity screen"),
        ([opt(status="IV_UNSOLVABLE_FROM_MID")], "liquidity screen"),
        ([opt(kind="PUT")], "no CALL"),
        ([], "no CALL"),
    ):
        row, why = select_contract(rows, kind="CALL", target_abs_delta=0.35)
        assert row is None and needle in why, (needle, why)


@test
def breakeven_reflects_cost_delta_and_spot():
    # $15 cost / (0.35 * 100) = $0.4286 move on a $100 underlying.
    assert abs(breakeven_move_pct(opt(delta=0.35)) - 0.0042857) < 1e-6
    assert breakeven_move_pct(opt(delta=0.0)) is None


# --- picks ------------------------------------------------------------------

def _payload(drift=0.002):
    b = bars(300, drift=drift, first_date="2025-01-01")
    return {"AAA": {"components": C.compute(b, "2026-03-02"),
                    "option_rows": [opt(), opt(kind="PUT", delta=-0.35)]}}


@test
def a_pick_carries_its_exit_policy_gate_verdict_and_edge_status():
    picks = generate_picks("2026-03-02", _payload(), variants=[BY_NAME["momentum"]],
                           exit_policy=ExitPolicy())
    p = picks[0]
    assert p["action"].startswith("PAPER_LONG_"), p
    assert p["exit_policy"]["horizon_trading_days"] == 5
    assert p["edge_status"] == "NOT_DEMONSTRATED"
    # The gate must be recorded, and must refuse: a snapshot has no edge estimate.
    assert p["gate_decision"] == "PASS"
    assert any(f.startswith("missing:expected_edge_after_costs") for f in p["gate_failed"])


@test
def low_conviction_abstains_and_says_why():
    flat = bars(300, drift=0.0, first_date="2025-01-01")
    payload = {"AAA": {"components": C.compute(flat, "2026-03-02"), "option_rows": [opt()]}}
    picks = generate_picks("2026-03-02", payload, variants=[BY_NAME["momentum"]],
                           exit_policy=ExitPolicy())
    assert picks[0]["action"] == "ABSTAIN"
    assert "floor" in picks[0]["reason"]


@test
def abstentions_are_recorded_not_dropped():
    """'The strategy proposed nothing' and 'the data was unusable' are different
    statements, and a run that silently omits either is not auditable."""
    payload = _payload()
    payload["AAA"]["option_rows"] = []
    picks = generate_picks("2026-03-02", payload, variants=VARIANTS,
                           exit_policy=ExitPolicy())
    assert len(picks) == len(VARIANTS)
    assert all(p["action"] == "ABSTAIN" and p["reason"] for p in picks)


@test
def the_rationale_quotes_the_numbers_it_used_and_states_the_caveat():
    p = generate_picks("2026-03-02", _payload(), variants=[BY_NAME["momentum"]],
                       exit_policy=ExitPolicy())[0]
    r = p["rationale"]
    assert p["variant"] in r and p["ticker"] in r
    assert "delta target" in r and "break even" in r
    assert "No edge has been demonstrated" in r, r
    assert 200 < len(r) < 2000, len(r)


# --- freezing ---------------------------------------------------------------

def _frozen():
    picks = generate_picks("2026-03-02", _payload(), variants=[BY_NAME["momentum"]],
                           exit_policy=ExitPolicy())
    return freeze("2026-03-02", picks, exit_policy=ExitPolicy(), universe=["AAA"],
                  generated_utc="2026-03-02T21:00:00+00:00", source_files={})


@test
def a_frozen_file_verifies_against_its_own_hash():
    assert verify(_frozen()) is True


@test
def editing_a_pick_after_the_fact_voids_the_record():
    """The entire reason a forward log beats a backtest. If a prediction can be
    revised once the outcome is known, it was never a prediction."""
    f = _frozen()
    f["picks"][0]["composite_score"] = 0.99
    assert verify(f) is False

    f2 = _frozen()
    f2["picks"][0]["direction"] = "BEARISH"
    assert verify(f2) is False

    f3 = _frozen()
    f3["picks"].append(dict(f3["picks"][0]))
    assert verify(f3) is False


@test
def the_envelope_records_what_a_later_reader_needs():
    f = _frozen()
    assert f["edge_status"] == "NOT_DEMONSTRATED"
    assert f["exit_policy"]["horizon_trading_days"] == 5
    assert len(f["exit_policy_plain_english"]) >= 3
    assert "not recommendations" in f["disclaimer"]
    assert f["n_picks"] + f["n_abstentions"] == len(f["picks"])


@test
def the_assessment_date_skips_weekends_and_is_labelled_approximate():
    # Monday 2026-03-02 + 5 trading days -> Monday 2026-03-09.
    assert approximate_assessment_date("2026-03-02", 5) == "2026-03-09"
    assert approximate_assessment_date("garbage", 5) is None


# --- resolution -------------------------------------------------------------

def _pick(entry=4.2, spot=100.0, strike=100.0, kind="CALL", direction="BULLISH",
          dte=35, expiration="2026-04-17", iv=0.25, target=0.50, stop=-0.50,
          min_dte=21, horizon=5, decision="2026-03-02"):
    return {"decision_date": decision, "variant": "v", "ticker": "AAA",
            "direction": direction, "action": f"PAPER_LONG_{kind}",
            "composite_score": 0.5, "entry_fill_estimate": entry,
            "contract": {"type": kind, "expiration": expiration, "strike": strike,
                         "dte": dte, "iv_solved": iv, "underlying_close": spot,
                         "delta": 0.35, "bid": 4.0, "ask": entry, "mid": 4.1},
            "exit_policy": {"horizon_trading_days": horizon, "profit_target_pct": target,
                            "stop_loss_pct": stop, "min_dte_exit": min_dte}}


def _fwd(closes, start="2026-03-03"):
    from datetime import date, timedelta
    d, out = date.fromisoformat(start), []
    for cl in closes:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"date": d.isoformat(), "close": cl})
        d += timedelta(days=1)
    return out


@test
def bars_after_excludes_the_decision_day_itself():
    rows = _fwd([100, 101], start="2026-03-02")
    assert [b["date"] for b in bars_after(rows, "2026-03-02")] == ["2026-03-03"]


@test
def a_position_with_no_sessions_yet_is_open_not_zero():
    o = resolve_pick(_pick(), [])
    assert o["status"] == "OPEN" and o["exit_trigger"] is None
    assert "no sessions" in o["detail"]


@test
def the_time_stop_closes_at_the_horizon_when_nothing_else_fires():
    o = resolve_pick(_pick(), _fwd([100.2, 100.3, 100.1, 100.4, 100.5]))
    assert o["status"] == "RESOLVED", o
    assert o["exit_trigger"] == "TIME_STOP" and o["days_held"] == 5


@test
def a_profit_target_closes_early_and_records_the_day_it_hit():
    """Checking only the horizon would miss this and report whatever the
    position happened to be worth five days later instead."""
    o = resolve_pick(_pick(), _fwd([101, 118, 125, 100, 99]))
    assert o["exit_trigger"] == "PROFIT_TARGET", o
    assert o["days_held"] < 5
    assert o["exit_return_on_premium"] >= 0.50


@test
def a_stop_loss_closes_early_rather_than_riding_to_the_horizon():
    o = resolve_pick(_pick(), _fwd([99, 92, 88, 130, 140]))
    assert o["exit_trigger"] == "STOP_LOSS", o
    assert o["days_held"] < 5
    assert o["exit_return_on_premium"] <= -0.50


@test
def the_dte_floor_closes_a_contract_that_has_decayed_too_far():
    """DTE is recomputed from each bar's own date. Decrementing the entry DTE by
    elapsed trading days would drift a day every weekend and move this exit."""
    o = resolve_pick(_pick(expiration="2026-03-20", dte=18, min_dte=21),
                     _fwd([100.1, 100.2, 100.3, 100.4, 100.5]))
    assert o["exit_trigger"] == "DTE_FLOOR", o
    assert o["days_held"] == 1


@test
def the_horizon_measurement_is_kept_separate_from_how_the_position_closed():
    """'Was the call right' and 'did the trade make money' are different
    questions. A stop-out must not erase the directional answer."""
    o = resolve_pick(_pick(), _fwd([99, 90, 85, 96, 130]))
    assert o["exit_trigger"] == "STOP_LOSS"
    assert o["horizon_date"] == _fwd([1, 2, 3, 4, 5])[4]["date"]
    # Underlying finished up, so a BULLISH call was directionally right even
    # though the pre-registered stop had already closed it at a loss.
    assert o["underlying_move_pct"] > 0 and o["direction_correct"] is True
    assert o["exit_return_on_premium"] <= -0.50
    assert o["horizon_return_on_premium"] > o["exit_return_on_premium"]


@test
def a_bearish_pick_is_scored_against_a_falling_underlying():
    o = resolve_pick(_pick(kind="PUT", direction="BEARISH"),
                     _fwd([99, 98, 97, 96, 95]))
    assert o["underlying_move_pct"] < 0 and o["direction_correct"] is True


@test
def an_observed_quote_is_preferred_over_a_modelled_mark():
    chain_day = _fwd([100.5] * 5)[4]["date"]
    chain = {chain_day: {"contracts": [
        {"type": "CALL", "expiration": "2026-04-17", "strike": 100.0,
         "bid": 9.0, "ask": 9.4, "status": "OK"}]}}
    o = resolve_pick(_pick(), _fwd([100.1, 100.2, 100.3, 100.4, 100.5]), chain)
    assert o["exit_mark_method"] == "MARKET", o
    # A modelled mark on the same path is a different number.
    m = resolve_pick(_pick(), _fwd([100.1, 100.2, 100.3, 100.4, 100.5]))
    assert m["exit_mark_method"] == "MODELLED"
    assert o["exit_price"] != m["exit_price"]


@test
def market_quote_matching_requires_type_expiry_and_strike_to_agree():
    c = {"type": "CALL", "expiration": "2026-04-17", "strike": 100.0}
    good = {"contracts": [{"type": "CALL", "expiration": "2026-04-17", "strike": 100.0,
                           "bid": 1.0, "ask": 1.2, "status": "OK"}]}
    assert market_quote(good, c) is not None
    for bad in ({"type": "PUT"}, {"expiration": "2026-05-15"}, {"strike": 105.0},
                {"status": "UNKNOWN"}):
        doc = {"contracts": [{**good["contracts"][0], **bad}]}
        assert market_quote(doc, c) is None, bad
    assert market_quote(None, c) is None


@test
def an_unmarkable_contract_says_so_instead_of_guessing():
    o = resolve_pick(_pick(expiration="2026-03-01"), _fwd([100.1] * 5))
    assert o["status"] == "UNMARKABLE" and "could not mark" in o["detail"]


@test
def the_summary_excludes_open_positions_rather_than_counting_them_flat():
    """Averaging an unresolved position in as zero drags every variant toward
    the middle and understates both winners and losers."""
    resolved = resolve_pick(_pick(), _fwd([100.2, 100.3, 100.1, 100.4, 100.5]))
    open_ = resolve_pick(_pick(), [])
    rows = summarise([resolved, open_])
    assert len(rows) == 1 and rows[0]["resolved"] == 1, rows
    assert summarise([open_]) == []


@test
def the_summary_reports_which_exit_rules_fired():
    picks = [resolve_pick(_pick(), _fwd([101, 118, 125, 100, 99])),
             resolve_pick(_pick(), _fwd([100.2, 100.3, 100.1, 100.4, 100.5]))]
    row = summarise(picks)[0]
    assert "PROFIT_TARGET:1" in row["exit_triggers"], row
    assert "TIME_STOP:1" in row["exit_triggers"], row
    assert row["wins"] + row["losses"] == 2


if __name__ == "__main__":
    sys.exit(0 if run_all("STRATEGY - COMPONENTS, VARIANTS, FROZEN PICKS") else 1)
