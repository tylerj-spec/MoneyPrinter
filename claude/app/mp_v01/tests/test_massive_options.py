#!/usr/bin/env python3
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime, timezone
from unittest.mock import patch
from harness import test, assert_raises, run_all
from adapters import massive_options as mv


def row(ticker="O:SPY260116C00500000", underlying="SPY", expiry="2026-01-16"):
    return {"ticker": ticker, "underlying_ticker": underlying, "contract_type": "call",
            "strike_price": 500.0, "expiration_date": expiry}


@test
def a_missing_key_raises_with_guidance_rather_than_a_silent_default():
    saved = os.environ.pop(mv.TOKEN_ENV_VAR, None)
    try: assert_raises(mv.MissingCredential, mv._token)
    finally:
        if saved is not None: os.environ[mv.TOKEN_ENV_VAR] = saved

@test
def the_key_is_scrubbed_from_any_text_before_it_can_be_logged():
    saved = os.environ.get(mv.TOKEN_ENV_VAR); os.environ[mv.TOKEN_ENV_VAR] = "SECRET-KEY-VALUE"
    try:
        out = mv.redact("HTTP error SECRET-KEY-VALUE")
        assert "SECRET-KEY-VALUE" not in out and "REDACTED" in out
    finally:
        if saved is None: os.environ.pop(mv.TOKEN_ENV_VAR, None)
        else: os.environ[mv.TOKEN_ENV_VAR] = saved

@test
def the_env_var_is_the_vendors_own_name(): assert mv.TOKEN_ENV_VAR == "MASSIVE_API_KEY"

@test
def a_contract_symbol_is_built_the_way_massive_spells_it():
    assert mv.contract_symbol("SPY", "2024-03-15", "CALL", 500.0) == "O:SPY240315C00500000"
    assert mv.contract_symbol("spy", "2024-03-15", "put", 4.5) == "O:SPY240315P00004500"

@test
def a_nonsense_contract_symbol_raises_rather_than_being_built():
    assert_raises(ValueError, mv.contract_symbol, "SPY", "2024-03-15", "CALLS", 500.0)
    assert_raises(ValueError, mv.contract_symbol, "SPY", "2024-03-15", "CALL", 0.0)

@test
def a_contract_row_carries_the_as_of_that_makes_it_point_in_time():
    out = mv.normalize_contract(row(), as_of="2024-03-05")
    assert out["as_of"] == "2024-03-05" and out["type"] == "CALL" and out["status"] == "OK"

@test
def a_nan_strike_becomes_unknown_rather_than_raising():
    out = mv.normalize_contract({**row(), "strike_price": float("nan")}, as_of="2024-03-05")
    assert out["strike"] is None and out["status"] == "UNKNOWN"

@test
def an_aggregate_timestamp_is_read_as_milliseconds_in_new_york():
    ms = int(datetime(2024, 3, 15, 13, 30, tzinfo=timezone.utc).timestamp() * 1000)
    out = mv.normalize_agg({"t": ms, "c": 1.1, "v": 250}, contract_symbol="X")
    assert out["date"] == "2024-03-15" and out["close"] == 1.1

@test
def an_aggregate_bar_is_not_available_at_its_own_close():
    assert mv.bar_available_time("2024-03-15") > mv.bar_event_time("2024-03-15")

@test
def a_proxy_refusing_a_tunnel_is_not_an_entitlement_verdict():
    assert mv.MassiveError("proxy says 403", "UNREACHABLE").kind == "UNREACHABLE"


def _ladder(responses, *, now=None):
    """Freeze the observation clock as well as the network.

    January 2026 is future relative to this fixture's September 2025 clock,
    not relative to the machine running CI. Do not move expirations forward
    every year or change the expected verdict to hide clock-dependent tests.
    """
    instant = now or datetime(2025, 9, 5, 16, 0, tzinfo=timezone.utc)
    calls = []

    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    def fake_get(path, params=None, **kw):
        calls.append(dict(params or {}))
        response = responses[len(calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    with patch.object(mv, "_get", fake_get), patch.object(mv, "datetime", FixtureClock):
        return mv.diagnose_access("SPY", "2025-08-01", pause_seconds=0), calls

@test
def ladder_uses_deterministic_samples_and_one_capability_parameter_per_rung():
    docs = [{"results": [row()]}] * 5
    steps, calls = _ladder(docs)
    base = {"limit", "sort", "order"}
    assert [set(c)-base for c in calls] == [
        set(), {"underlying_ticker"}, {"underlying_ticker", "expired"},
        {"underlying_ticker", "expired", "expiration_date.gte"},
        {"underlying_ticker", "expired", "expiration_date.gte", "as_of"}]
    assert all(c["sort"] == "ticker" and c["order"] == "asc" for c in calls)
    assert steps[-1]["verdict"] == "UNVERIFIED", steps[-1]

@test
def ignored_underlying_is_caught_immediately():
    cyu = {"results": [row("O:CYU121222C00060000", "CYU", "2012-12-22")]}
    steps, _ = _ladder([cyu]*5)
    assert steps[1]["verdict"] == "IGNORED" and "CYU" in steps[1]["detail"]

@test
def expired_true_is_not_claimed_verified_without_an_expired_sample():
    steps, _ = _ladder([{"results":[row()]}]*5)
    assert steps[2]["verdict"] == "UNVERIFIED", steps[2]

@test
def expiry_verdict_changes_only_when_the_injected_clock_crosses_expiry():
    docs = [{"results": [row()]}] * 5
    for year, expected in ((2025, "UNVERIFIED"), (2026, "OK"), (2030, "OK")):
        steps, _ = _ladder(docs, now=datetime(year, 9, 5, 16, tzinfo=timezone.utc))
        assert steps[2]["verdict"] == expected, (year, steps[2])
    assert mv.datetime is datetime, "the test clock must never leak into other tests"

@test
def expired_true_is_verified_when_sample_contains_an_already_expired_contract():
    old = row("O:SPY250101C00500000", "SPY", "2025-01-01")
    future = row()
    steps, _ = _ladder([{"results":[future]}, {"results":[future]}, {"results":[old]},
                        {"results":[future]}, {"results":[row("O:SPY251219C00500000", "SPY", "2025-12-19")]}])
    assert steps[2]["verdict"] == "OK", steps[2]

@test
def expiration_floor_is_mechanically_enforced():
    stale = row("O:SPY250701C00500000", "SPY", "2025-07-01")
    future = row()
    steps, _ = _ladder([{"results":[future]}, {"results":[future]}, {"results":[future]},
                        {"results":[stale]}, {"results":[future]}])
    assert steps[3]["verdict"] == "IGNORED", steps[3]

@test
def as_of_is_only_consistent_when_it_changes_the_deterministic_sample():
    before = row("O:SPY260116C00500000", "SPY", "2026-01-16")
    after = row("O:SPY251219C00500000", "SPY", "2025-12-19")
    steps, _ = _ladder([{"results":[before]}, {"results":[before]}, {"results":[before]},
                        {"results":[before]}, {"results":[after]}])
    assert steps[4]["verdict"] == "CONSISTENT", steps[4]

@test
def empty_does_not_magically_become_proof():
    future = {"results":[row()]}
    steps, calls = _ladder([future, future, future, {"results":[]}, future])
    assert steps[3]["verdict"] == "EMPTY" and len(calls) == 5

@test
def refusal_stops_the_ladder():
    steps, calls = _ladder([{"results":[row()]}, mv.MassiveError("HTTP 403", "NOT_ENTITLED")])
    assert len(steps) == len(calls) == 2 and steps[-1]["verdict"] == "NOT_ENTITLED"

@test
def malformed_diagnostic_date_spends_no_calls():
    assert_raises(ValueError, mv.diagnose_access, "SPY", "not-a-date", 0)

@test
def endpoint_paths_are_pinned():
    assert mv.CONTRACTS_PATH == "/v3/reference/options/contracts"
    assert mv.AGGS_PATH == "/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_}/{to}"
    assert mv.CHAIN_SNAPSHOT_PATH == "/v3/snapshot/options/{underlying}"


if __name__ == "__main__":
    sys.exit(0 if run_all("MASSIVE OPTIONS ADAPTER (offline)") else 1)
