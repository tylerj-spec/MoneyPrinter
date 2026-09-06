from paper.quotes import marketable_long_limit_fill, quote_quality


def q(**kw):
    observed = kw.pop("observed_utc", "2026-09-04T19:44:30Z")
    x = {"contract_id": "SPY261016C00600000", "source": "SYNTHETIC_FIXTURE",
         "bid": 1.9, "ask": 2.0, "bid_size": 5, "ask_size": 5,
         "observed_utc": observed, "available_utc": observed,
         "feed_type": "OPRA", "delayed": False, "size_units": "CONTRACTS"}
    x.update(kw)
    return x


def test_quote_must_precede_decision_and_be_fresh():
    assert quote_quality(q(), decision_utc="2026-09-04T19:45:00Z")[0]
    assert quote_quality(q(observed_utc="2026-09-04T19:46:00Z"), decision_utc="2026-09-04T19:45:00Z")[1] == "lookahead_quote"
    assert quote_quality(q(observed_utc="2026-09-04T19:40:00Z"), decision_utc="2026-09-04T19:45:00Z")[1] == "stale_quote"


def test_indicative_feed_is_not_executable():
    assert quote_quality(q(feed_type="INDICATIVE"), decision_utc="2026-09-04T19:45:00Z")[1] == "non_executable_feed_type"


def test_fill_respects_limit_and_displayed_size():
    timing = {"submitted_utc": "2026-09-04T19:44:00Z", "execution_utc": "2026-09-04T19:45:00Z"}
    assert marketable_long_limit_fill(q(), limit_price=2.0, quantity=1, **timing) == (True, 2.0, "filled_at_ask")
    assert marketable_long_limit_fill(q(), limit_price=1.99, quantity=1, **timing)[2] == "not_marketable"
    assert marketable_long_limit_fill(q(ask_size=0), limit_price=2.0, quantity=1, **timing)[2] == "insufficient_displayed_size"
    assert not marketable_long_limit_fill(q(), limit_price=2.0)[0]
