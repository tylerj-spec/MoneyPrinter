from gates.risk import Decision, evaluate

BASE={"independent_events":2,"evidence_confidence":0.8,"dte":40,"relative_spread":0.05,
      "open_interest":1000,"daily_volume":100,"defined_risk":True,"expected_edge_after_costs":0.1}

def test_missing_portfolio_context_fails_closed():
    r=evaluate(dict(BASE))
    assert r.decision == Decision.PASS
    assert {"missing:position_pct","missing:portfolio_heat_pct","missing:open_positions"} <= set(r.failed_gates)

def test_complete_safe_context_can_be_candidate():
    r=evaluate({**BASE,"position_pct":0.01,"portfolio_heat_pct":0.03,"open_positions":1})
    assert r.decision == Decision.PAPER_TRADE_CANDIDATE

def test_defined_risk_must_be_actual_true():
    r=evaluate({**BASE,"defined_risk":1,"position_pct":0.01,"portfolio_heat_pct":0.03,"open_positions":1})
    assert "undefined_risk_structure" in r.failed_gates


def test_invalid_domains_are_not_safe_context():
    safe = {**BASE, "position_pct": .01, "portfolio_heat_pct": .03, "open_positions": 1}
    for field, value in (("position_pct", -1), ("position_pct", 0),
                         ("portfolio_heat_pct", -1), ("open_positions", .5),
                         ("relative_spread", -.1), ("evidence_confidence", 1.1),
                         ("independent_events", 2.5)):
        r = evaluate({**safe, field: value})
        assert r.decision == Decision.PASS, (field, r)
    assert evaluate({**safe, "portfolio_heat_pct": .001}).decision == Decision.PASS
