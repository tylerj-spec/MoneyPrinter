"""Integration coverage retained from the original PR13 scaffold."""
from paper.ledger import PaperAccount, PaperPosition, proposal_context, apply_long_fill
from paper.quotes import quote_quality, marketable_long_limit_fill


def test_paper_stack():
    account = PaperAccount(1000, 1000)
    assert proposal_context(account, entry_price=2.0)["position_pct"] == .2
    position = PaperPosition("p", "SPY", "c", 1, 2)
    assert apply_long_fill(account, position).cash == 800
    incomplete = {"bid": 1.9, "ask": 2, "ask_size": 1, "observed_utc": "2026-09-04T19:44:30Z", "feed_type": "OPRA"}
    assert not quote_quality(incomplete, decision_utc="2026-09-04T19:45:00Z")[0]
    assert not marketable_long_limit_fill(incomplete, limit_price=2)[0]


def test_quote_lookahead_and_indicative_fail():
    q = {"contract_id": "c", "source": "SYNTHETIC", "bid": 1.9, "ask": 2,
         "bid_size": 1, "ask_size": 1, "size_units": "CONTRACTS", "delayed": False,
         "observed_utc": "2026-09-04T19:46:00Z", "available_utc": "2026-09-04T19:46:00Z", "feed_type": "OPRA"}
    assert quote_quality(q, decision_utc="2026-09-04T19:45:00Z")[1] == "lookahead_quote"
    q.update(observed_utc="2026-09-04T19:44:30Z", available_utc="2026-09-04T19:44:30Z", feed_type="INDICATIVE")
    assert quote_quality(q, decision_utc="2026-09-04T19:45:00Z")[1] == "non_executable_feed_type"
