from backtest.replay import eligible_observations, latest_predecision_quote, replay_fill

ROWS=[
 {"contract_id":"c","observed_utc":"2026-01-02T19:44:00Z","available_utc":"2026-01-02T19:44:02Z","bid":1.9,"ask":2.0,"source":"x"},
 {"contract_id":"c","observed_utc":"2026-01-02T19:44:30Z","available_utc":"2026-01-02T19:45:01Z","bid":2.0,"ask":2.1,"source":"x"},
 {"contract_id":"c","observed_utc":"2026-01-02T19:46:00Z","available_utc":"2026-01-02T19:46:01Z","bid":2.2,"ask":2.3,"source":"x"},]

def test_availability_not_just_observation_controls_lookahead():
    e=eligible_observations(ROWS,decision_utc="2026-01-02T19:45:00Z",contract_id="c")
    assert len(e)==1 and e[0]["ask"]==2.0

def test_replay_never_invents_missing_quote():
    assert latest_predecision_quote([],decision_utc="2026-01-02T19:45:00Z",contract_id="c") is None
    assert replay_fill(None,side="BUY")["status"]=="NO_FILL"

def test_buy_uses_ask_and_preserves_provenance():
    f=replay_fill(ROWS[0],side="BUY")
    assert f["price"]==2.0 and f["source"]=="x" and f["observed_utc"].endswith("Z")
