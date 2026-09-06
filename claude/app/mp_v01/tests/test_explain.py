from strategy.explain import build_explanation


def test_explanation_is_short_and_traceable():
    kwargs = dict(
        ticker="SPY", variant="balanced", direction="BULLISH", composite_score=0.73,
        contract={"type": "CALL", "expiration": "2026-10-16", "strike": 650,
                  "delta": 0.52, "dte": 41},
        components_scaled={"return_20d": 0.8, "realised_vol_20d": -0.2, "trend": 0.4},
        weights={"return_20d": 0.5, "realised_vol_20d": 0.2, "trend": 0.3},
        selection_policy={"mode": "delta"}, selection_metrics={"delta_gap": 0.02},
        decision_date="2026-09-05",
    )
    a = build_explanation(**kwargs)
    b = build_explanation(**kwargs)
    assert "SPY scored +0.73" in a["short_justification"]
    assert "2026-10-16" in a["short_justification"]
    assert a["details"]["top_weighted_drivers"][0]["indicator"] == "return_20d"
    assert a["details_fingerprint_sha256"] == b["details_fingerprint_sha256"]


def test_explanation_fingerprint_changes_with_input():
    common = dict(
        ticker="SPY", variant="v", direction="BULLISH", composite_score=0.5,
        contract={"type":"CALL","expiration":"2026-10-16","strike":650,"delta":0.5,"dte":40},
        components_scaled={"trend": 0.4}, weights={"trend": 1.0},
        selection_policy={"mode":"delta"}, selection_metrics={}, decision_date="2026-09-05")
    a = build_explanation(**common)
    common["components_scaled"] = {"trend": 0.5}
    b = build_explanation(**common)
    assert a["details_fingerprint_sha256"] != b["details_fingerprint_sha256"]


def test_explanation_owns_inputs_and_explains_actual_contributions():
    from strategy.explain import attach_explanation, verify_explanation
    p = {"ticker": "AAA", "variant": "v", "direction": "BULLISH", "composite_score": .1,
         "contract": {"type": "CALL", "expiration": "2026-10-16", "strike": 100},
         "components_scaled": {"a": .5, "b": -.2}, "weights": {"a": .4, "b": .5}}
    result = attach_explanation(p)
    e = result["explanation"]
    assert e["details"]["score_matches_components"]
    p["weights"]["a"] = 999
    assert verify_explanation(e)
    e["details"]["weights"]["a"] = 999
    assert not verify_explanation(e)


def test_every_generated_pick_and_abstention_has_drilldown():
    from strategy.picks import generate_picks, ExitPolicy, freeze, verify
    from strategy.variants import BY_NAME
    from test_strategy_picks import opt
    data = {"AAA": {"components": {"raw": {}, "scaled": {"momentum_20d": .8,
           "momentum_60d": .6, "trend_50d": .7}}, "option_rows": [opt()]},
            "BBB": {"precondition_reason": "no quote"}}
    picks = generate_picks("2026-03-02", data, variants=[BY_NAME["momentum"]], exit_policy=ExitPolicy())
    assert len(picks) == 2 and all(p["short_justification"] for p in picks)
    record = freeze("2026-03-02", picks, exit_policy=ExitPolicy(), universe=["AAA", "BBB"],
                    generated_utc="2026-03-02T19:00:00Z", source_files={"source_hash": "test"})
    assert verify(record)
    assert record["picks"][0]["explanation"]["details"]["context"]["source_files"]["source_hash"] == "test"
    record["picks"][0]["short_justification"] += "edited"
    assert not verify(record)
