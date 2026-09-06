from strategy.resolve import summarise, _direction_label


def test_selection_policies_are_never_pooled():
    rows = [{"status": "RESOLVED", "variant": "v", "selection_policy": {"mode": p},
             "pick_contract_version": "0.5.0", "exit_path_provenance": "OBSERVED_ONLY",
             "exit_return_on_premium": ret} for p, ret in (("delta", .2), ("cost_aware", -.3))]
    result = summarise(rows)
    assert len(result) == 2
    assert {r["selection_policy"] for r in result} == {"delta", "cost_aware"}


def test_misaligned_instrument_and_benchmark_windows_are_unscored():
    bars = [{"date": f"2026-01-{day:02d}", "close": 100+day, "daily_total_return": .01}
            for day in (2, 5, 6, 7, 8, 9)]
    benchmark = [{"date": f"2026-01-{day:02d}", "close": 100+day, "daily_total_return": .01}
                 for day in (2, 5, 6, 7, 9, 12)]
    assert _direction_label("AAA", "2026-01-02", bars, benchmark, 5) is None
