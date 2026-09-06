"""Timestamped observed-quote validation and conservative marketable-limit fills."""
from __future__ import annotations
from datetime import timedelta
from common.validation import digest, iso, number, utc, whole

EXECUTABLE_FEEDS = frozenset({"OPRA", "NBBO", "CONSOLIDATED"})


def quote_quality(q: dict, *, decision_utc: str, max_age_seconds: int = 60) -> tuple[bool, str]:
    try:
        if not isinstance(q, dict):
            raise ValueError("quote object required")
        bid = number(q["bid"], "bid", minimum=0)
        ask = number(q["ask"], "ask", minimum=0)
        observed = utc(q["observed_utc"])
        available = utc(q["available_utc"])
        bid_time = utc(q.get("bid_utc", q["observed_utc"]))
        ask_time = utc(q.get("ask_utc", q["observed_utc"]))
        cutoff = utc(decision_utc)
        age_limit = number(max_age_seconds, "max_age_seconds", minimum=0)
        if not q.get("contract_id") or not q.get("source"):
            return False, "missing_contract_or_source"
        if available < max(observed, bid_time, ask_time):
            return False, "impossible_availability"
        if max(observed, available, bid_time, ask_time) > cutoff:
            return False, "lookahead_quote"
        if (cutoff - min(observed, bid_time, ask_time)).total_seconds() > age_limit:
            return False, "stale_quote"
        if ask <= 0 or bid > ask:
            return False, "crossed_or_invalid_market"
        if q.get("feed_type") not in EXECUTABLE_FEEDS or q.get("delayed") is not False:
            return False, "non_executable_feed_type"
        if q.get("size_units") != "CONTRACTS":
            return False, "unverified_size_units"
        whole(q["bid_size"], "bid_size")
        whole(q["ask_size"], "ask_size")
    except (ValueError, KeyError, TypeError, OverflowError):
        return False, "malformed_quote"
    return True, "eligible"


def quote_identity(q: dict) -> str:
    """Receipt time is excluded: re-downloading an unchanged book creates no liquidity."""
    keys = ("contract_id", "source", "feed_type", "bid", "ask", "bid_size", "ask_size",
            "bid_utc", "ask_utc", "observed_utc")
    return digest({k: q.get(k) for k in keys})


def simulate_fill(q: dict, *, side: str, limit_price: float, quantity: int,
                  submitted_utc: str, execution_utc: str, latency_seconds: float = 1,
                  consumed_size: int = 0, max_age_seconds: int = 60) -> dict:
    """A decision quote cannot fill its own order. No crossing implies no fill."""
    try:
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        quantity = whole(quantity, "quantity", minimum=1)
        consumed_size = whole(consumed_size, "consumed_size")
        limit_price = number(limit_price, "limit_price", minimum=0)
        latency = number(latency_seconds, "latency_seconds", minimum=0.000001)
        submitted, execution = utc(submitted_utc), utc(execution_utc)
        if limit_price <= 0 or execution < submitted:
            raise ValueError("invalid limit or execution time")
    except ValueError:
        return {"status": "NO_FILL", "reason": "invalid_order"}
    good, reason = quote_quality(q, decision_utc=execution_utc, max_age_seconds=max_age_seconds)
    if not good:
        return {"status": "NO_FILL", "reason": reason}
    side_time = utc(q.get("ask_utc" if side == "BUY" else "bid_utc", q["observed_utc"]))
    if side_time < submitted + timedelta(seconds=latency):
        return {"status": "NO_FILL", "reason": "no_post_submission_quote"}
    price = q["ask" if side == "BUY" else "bid"]
    if price <= 0 or (side == "BUY" and price > limit_price) or (side == "SELL" and price < limit_price):
        return {"status": "NO_FILL", "reason": "not_marketable"}
    available = max(0, q["ask_size" if side == "BUY" else "bid_size"] - consumed_size)
    qty = min(quantity, available)
    if not qty:
        return {"status": "NO_FILL", "reason": "insufficient_displayed_size"}
    return {"status": "FILLED" if qty == quantity else "PARTIAL_FILL", "quantity": qty,
            "price": price, "quote_id": quote_identity(q), "observed_utc": iso(q["observed_utc"]),
            "available_utc": iso(q["available_utc"]), "source": q["source"], "side": side}


def marketable_long_limit_fill(q: dict, *, limit_price: float, quantity: int = 1,
                               submitted_utc: str | None = None,
                               execution_utc: str | None = None) -> tuple[bool, float | None, str]:
    """Compatibility wrapper; timing is mandatory instead of silently assuming a fill."""
    if submitted_utc is None or execution_utc is None:
        return False, None, "submission_and_execution_timestamps_required"
    fill = simulate_fill(q, side="BUY", limit_price=limit_price, quantity=quantity,
                         submitted_utc=submitted_utc, execution_utc=execution_utc)
    if fill["status"] == "FILLED":
        return True, fill["price"], "filled_at_ask"
    return False, None, fill.get("reason", "partial_fill_use_simulate_fill")
