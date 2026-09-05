#!/usr/bin/env python3
"""
Tests for the Massive (formerly Polygon.io) historical options adapter.

    python tests/test_massive_options.py

Nothing here touches the network. That is deliberate and it is the lesson from
the chain-NaN bug: logic that lives inside a network call cannot be tested, and
what cannot be tested is where the defects were found by a user instead.

Every field name and path asserted below was read out of the vendor's own
client (github.com/massive-com/client-python), not remembered.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime, timezone

from harness import test, assert_raises, run_all
from adapters import massive_options as mv


# ---------- credential hygiene ----------
@test
def a_missing_key_raises_with_guidance_rather_than_a_silent_default():
    saved = os.environ.pop(mv.TOKEN_ENV_VAR, None)
    try:
        assert_raises(mv.MissingCredential, mv._token)
    finally:
        if saved is not None:
            os.environ[mv.TOKEN_ENV_VAR] = saved

@test
def the_key_is_scrubbed_from_any_text_before_it_can_be_logged():
    saved = os.environ.get(mv.TOKEN_ENV_VAR)
    os.environ[mv.TOKEN_ENV_VAR] = "SECRET-KEY-VALUE"
    try:
        msg = "HTTP 403 on /v3/reference/options/contracts: key SECRET-KEY-VALUE denied"
        out = mv.redact(msg)
        assert "SECRET-KEY-VALUE" not in out, out
        assert "REDACTED" in out
    finally:
        if saved is None:
            os.environ.pop(mv.TOKEN_ENV_VAR, None)
        else:
            os.environ[mv.TOKEN_ENV_VAR] = saved

@test
def the_env_var_is_the_vendors_own_name():
    assert mv.TOKEN_ENV_VAR == "MASSIVE_API_KEY"


# ---------- contract symbols ----------
@test
def a_contract_symbol_is_built_the_way_massive_spells_it():
    """OCC-style: O:SPY240315C00500000. Strike in thousandths, eight digits."""
    assert mv.contract_symbol("SPY", "2024-03-15", "CALL", 500.0) == "O:SPY240315C00500000"
    assert mv.contract_symbol("spy", "2024-03-15", "put", 4.5) == "O:SPY240315P00004500"
    assert mv.contract_symbol("NVDA", "2026-01-16", "CALL", 1234.5) == "O:NVDA260116C01234500"

@test
def a_nonsense_contract_symbol_raises_rather_than_being_built():
    assert_raises(ValueError, mv.contract_symbol, "SPY", "2024-03-15", "CALLS", 500.0)
    assert_raises(ValueError, mv.contract_symbol, "SPY", "2024-03-15", "CALL", 0.0)
    assert_raises(ValueError, mv.contract_symbol, "SPY", "2024-03-15", "CALL", -5.0)


# ---------- contract rows ----------
@test
def a_contract_row_carries_the_as_of_that_makes_it_point_in_time():
    """as_of is the entire reason the row is trustworthy: it says the contract
    existed that day, not that it exists now and might have been listed later."""
    row = {"ticker": "O:SPY240315C00500000", "underlying_ticker": "SPY",
           "contract_type": "call", "strike_price": 500.0,
           "expiration_date": "2024-03-15", "exercise_style": "american",
           "shares_per_contract": 100}
    out = mv.normalize_contract(row, as_of="2024-03-05")
    assert out["as_of"] == "2024-03-05"
    assert out["type"] == "CALL" and out["strike"] == 500.0
    assert out["shares_per_contract"] == 100 and out["status"] == "OK"

@test
def a_contract_missing_what_makes_it_a_contract_is_unknown_not_dropped():
    for bad in ({"ticker": "X", "contract_type": "call", "expiration_date": "2024-03-15"},
                {"ticker": "X", "strike_price": 5.0, "expiration_date": "2024-03-15"},
                {"contract_type": "put", "strike_price": 5.0, "expiration_date": "2024-03-15"}):
        out = mv.normalize_contract(bad, as_of="2024-03-05")
        assert out["status"] == "UNKNOWN", (bad, out)

@test
def a_nan_strike_becomes_unknown_rather_than_raising():
    """The bug that emptied every Yahoo chain, pre-empted here."""
    out = mv.normalize_contract(
        {"ticker": "X", "contract_type": "call", "strike_price": float("nan"),
         "expiration_date": "2024-03-15", "shares_per_contract": float("nan")},
        as_of="2024-03-05")
    assert out["strike"] is None and out["shares_per_contract"] is None
    assert out["status"] == "UNKNOWN"


# ---------- aggregate rows ----------
@test
def an_aggregate_timestamp_is_read_as_milliseconds_in_new_york():
    """Two off-by-ones live here. `t` is epoch MILLISECONDS - reading it as
    seconds puts every bar in 1970. And the date must be taken in ET: a bar
    stamped late in the session is the NEXT day in UTC."""
    ms = int(datetime(2024, 3, 15, 13, 30, tzinfo=timezone.utc).timestamp() * 1000)
    out = mv.normalize_agg({"t": ms, "o": 1.0, "h": 1.2, "l": 0.9, "c": 1.1,
                            "v": 250, "vw": 1.05, "n": 40},
                           contract_symbol="O:SPY240315C00500000")
    assert out["date"] == "2024-03-15", out
    assert out["close"] == 1.1 and out["volume"] == 250 and out["status"] == "OK"

@test
def a_late_session_bar_does_not_roll_into_the_next_day():
    """20:00 ET on the 15th is 00:00 UTC on the 16th. Reading the UTC date
    would file that bar under the wrong session."""
    ms = int(datetime(2024, 3, 16, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert mv.normalize_agg({"t": ms, "c": 1.0}, contract_symbol="X")["date"] == "2024-03-15"

@test
def an_aggregate_bar_is_not_available_at_its_own_close():
    """The single easiest lookahead: treating a bar as usable on its own date."""
    avail = mv.bar_available_time("2024-03-15")
    event = mv.bar_event_time("2024-03-15")
    assert avail > event, (avail, event)
    assert (avail - event).total_seconds() == mv.BAR_AVAILABILITY_LAG_HOURS * 3600

@test
def an_unreadable_aggregate_is_unknown_and_carries_no_nan():
    import json
    out = mv.normalize_agg({"t": None, "c": float("nan"), "v": float("nan")},
                           contract_symbol="X")
    assert out["status"] == "UNKNOWN" and out["date"] is None
    assert out["close"] is None and out["volume"] is None
    json.dumps(out, default=str, allow_nan=False)   # raises if a NaN survived


# ---------- error classification ----------
@test
def a_proxy_refusing_a_tunnel_is_not_an_entitlement_verdict():
    """Caught by the first smoke test of this adapter.

    An HTTPS proxy that declines to open a tunnel says "403 Forbidden", and a
    classifier looking for "403" in the message reported NOT_ENTITLED - which
    would send the reader to check a subscription when the host was simply
    unreachable. The kind is now recorded where the error is raised, by the
    only code that knows which happened.
    """
    unreachable = mv.MassiveError(
        "cannot reach https://api.massive.com: Tunnel connection failed: 403 Forbidden",
        "UNREACHABLE")
    assert unreachable.kind == "UNREACHABLE", "a 403 in the TEXT must not decide this"
    assert mv.MassiveError("HTTP 403 on /v3/...: not entitled", "NOT_ENTITLED").kind \
        == "NOT_ENTITLED"
    assert mv.MassiveError("something else").kind == "ERROR"


# ---------- the paths, pinned ----------
@test
def the_endpoint_paths_are_the_ones_the_vendor_client_uses():
    """Read verbatim from massive/rest/reference.py and massive/rest/aggs.py.
    Pinned so a rebrand or version bump is a failing test, not a 404 at runtime."""
    assert mv.CONTRACTS_PATH == "/v3/reference/options/contracts"
    assert mv.AGGS_PATH == "/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_}/{to}"
    assert mv.CHAIN_SNAPSHOT_PATH == "/v3/snapshot/options/{underlying}"
    assert mv.BASE_URL == "https://api.massive.com"


if __name__ == "__main__":
    sys.exit(0 if run_all("MASSIVE OPTIONS ADAPTER (offline)") else 1)
