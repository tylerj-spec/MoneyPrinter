from paper.quotes import marketable_long_limit_fill, quote_quality

def q(**kw):
    x={"bid":1.9,"ask":2.0,"ask_size":5,"observed_utc":"2026-09-05T19:44:30Z","feed_type":"OPRA"}; x.update(kw); return x

def test_quote_must_precede_decision_and_be_fresh():
    assert quote_quality(q(),decision_utc="2026-09-05T19:45:00Z")[0]
    assert quote_quality(q(observed_utc="2026-09-05T19:46:00Z"),decision_utc="2026-09-05T19:45:00Z")[1]=="lookahead_quote"
    assert quote_quality(q(observed_utc="2026-09-05T19:40:00Z"),decision_utc="2026-09-05T19:45:00Z")[1]=="stale_quote"

def test_indicative_feed_is_not_executable():
    assert quote_quality(q(feed_type="INDICATIVE"),decision_utc="2026-09-05T19:45:00Z")[1]=="non_executable_feed_type"

def test_fill_respects_limit_and_displayed_size():
    assert marketable_long_limit_fill(q(),limit_price=2.0,quantity=1)==(True,2.0,"filled_at_ask")
    assert marketable_long_limit_fill(q(),limit_price=1.99,quantity=1)[2]=="not_marketable"
    assert marketable_long_limit_fill(q(ask_size=0),limit_price=2.0,quantity=1)[2]=="insufficient_displayed_size"
