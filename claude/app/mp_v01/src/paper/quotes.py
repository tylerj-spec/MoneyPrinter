from datetime import datetime
def quote_quality(q,*,decision_utc,max_age_seconds=60):
 try: bid=float(q["bid"]);ask=float(q["ask"]);observed=datetime.fromisoformat(str(q["observed_utc"]).replace("Z","+00:00"));decision=datetime.fromisoformat(decision_utc.replace("Z","+00:00"))
 except (KeyError,TypeError,ValueError): return False,"malformed_quote"
 if observed.tzinfo is None or decision.tzinfo is None:return False,"timezone_required"
 if bid<0 or ask<=0 or ask<bid:return False,"crossed_or_invalid_market"
 age=(decision-observed).total_seconds()
 if age<0:return False,"lookahead_quote"
 if age>max_age_seconds:return False,"stale_quote"
 if q.get("feed_type") not in {"OPRA","NBBO","CONSOLIDATED"}:return False,"non_executable_feed_type"
 return True,"eligible"
def marketable_long_limit_fill(q,*,limit_price,quantity=1):
 if quantity<=0 or limit_price<=0:return False,None,"invalid_order"
 ask=float(q.get("ask",0));size=q.get("ask_size")
 if limit_price<ask:return False,None,"not_marketable"
 if size is not None and int(size)<quantity:return False,None,"insufficient_displayed_size"
 return True,ask,"filled_at_ask"
