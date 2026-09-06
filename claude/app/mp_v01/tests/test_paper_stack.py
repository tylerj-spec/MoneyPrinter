from paper.ledger import *
from paper.quotes import *
def test_paper_stack():
 a=PaperAccount(1000,1000);c=proposal_context(a,entry_price=2.0);assert c["position_pct"]==.2
 p=PaperPosition("p","SPY","c",1,2);b=apply_long_fill(a,p);assert b.cash==800
 q={"bid":1.9,"ask":2.0,"ask_size":1,"observed_utc":"2026-09-05T19:44:30Z","feed_type":"OPRA"}
 assert quote_quality(q,decision_utc="2026-09-05T19:45:00Z")[0]
 assert marketable_long_limit_fill(q,limit_price=2.0)[0]
def test_quote_lookahead_and_indicative_fail():
 q={"bid":1.9,"ask":2.0,"observed_utc":"2026-09-05T19:46:00Z","feed_type":"OPRA"}
 assert quote_quality(q,decision_utc="2026-09-05T19:45:00Z")[1]=="lookahead_quote"
 q["observed_utc"]="2026-09-05T19:44:30Z";q["feed_type"]="INDICATIVE"
 assert quote_quality(q,decision_utc="2026-09-05T19:45:00Z")[1]=="non_executable_feed_type"
