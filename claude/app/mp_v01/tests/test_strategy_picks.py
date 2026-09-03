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


if __name__ == "__main__":
    sys.exit(0 if run_all("STRATEGY - COMPONENTS, VARIANTS, FROZEN PICKS") else 1)
