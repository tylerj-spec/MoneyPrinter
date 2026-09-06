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
