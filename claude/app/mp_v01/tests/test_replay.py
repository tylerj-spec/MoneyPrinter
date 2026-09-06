from pathlib import Path
import sys
import copy
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from backtest.replay import eligible_observations, latest_predecision_quote, replay_fill, run_replay
from replay_options import demo_dataset


def test_availability_not_just_observation_controls_lookahead():
    rows = [{"contract_id": "c", "observed_utc": "2026-01-02T19:44:00Z", "available_utc": "2026-01-02T19:44:02Z"},
            {"contract_id": "c", "observed_utc": "2026-01-02T19:44:00Z", "available_utc": "2026-01-02T19:46:02Z"}]
    assert len(eligible_observations(rows, decision_utc="2026-01-02T19:45:00Z", contract_id="c")) == 1


def test_replay_never_invents_missing_quote():
    assert latest_predecision_quote([], decision_utc="2026-01-02T19:45:00Z", contract_id="c") is None
    assert replay_fill(None, side="BUY")["status"] == "NO_FILL"


def test_predecision_quote_cannot_fill_its_own_order():
    q = demo_dataset()["quotes"][0]
    assert replay_fill(q, side="BUY")["status"] == "NO_FILL"
    assert replay_fill(q, side="BAD", submitted_utc="2026-09-04T15:00:00Z", execution_utc="2026-09-04T15:00:02Z", limit_price=20)["status"] == "NO_FILL"


def test_replay_and_both_policies_have_explanations_and_observed_outcomes():
    result = run_replay(demo_dataset())
    assert len(result["pick_records"]) == 2
    assert all(r["status"] == "RESOLVED" for r in result["outcomes"])
    for record in result["pick_records"]:
        p = record["picks"][0]
        assert p["short_justification"] and p["explanation"]["details"]["indicator_contributions"]
        assert p["run_mode"] == "HISTORICAL_REPLAY"
        assert "decision_inputs_file" in record["source_files"]


def test_future_prices_change_outcomes_not_frozen_decision_explanations():
    original = demo_dataset()
    changed = copy.deepcopy(original)
    for q in changed["quotes"]:
        if "15:10:02" in q["observed_utc"]:
            q["bid"] *= 1.5
            q["ask"] *= 1.5
    a = run_replay(original, generated_utc="2026-09-05T12:00:00Z")
    b = run_replay(changed, generated_utc="2026-09-05T12:00:00Z")
    assert a["pick_records"] == b["pick_records"]
    assert a["outcomes"] != b["outcomes"]


def test_missing_exit_quotes_are_unresolved_not_modelled_or_zero():
    ds = demo_dataset()
    ds["quotes"] = [q for q in ds["quotes"] if "15:10:02" not in q["observed_utc"]]
    out = run_replay(ds)
    assert all(o["status"] == "UNRESOLVED" and o["net_pnl"] is None for o in out["outcomes"])


def test_future_listings_and_missing_underlying_quote_abstain():
    ds = demo_dataset()
    for spec in ds["contracts"]:
        spec["known_utc"] = "2026-09-05T00:00:00Z"
    assert all(o["status"] == "ABSTAIN" for o in run_replay(ds)["outcomes"])
    ds = demo_dataset(); ds["underlying_quotes"] = []
    assert all(o["status"] == "ABSTAIN" for o in run_replay(ds)["outcomes"])


def test_unknown_session_and_future_rate_fail_closed():
    for field in ("sessions", "rate"):
        ds = demo_dataset()
        if field == "sessions":
            ds[field] = []
        else:
            ds[field]["available_utc"] = "2030-01-01T00:00:00Z"
        try:
            run_replay(ds)
        except ValueError:
            pass
        else:
            assert False
