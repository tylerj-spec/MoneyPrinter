"""Deterministic observed-quote paper execution and restart/accounting tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
from paper.ledger import PaperLedger
from paper.quotes import simulate_fill

T = "2026-09-04T15:00:00Z"
C = {"contract_id": "SPY261016C00600000", "standard_contract": True, "premium_multiplier": 100, "deliverable_shares": 100, "expiration": "2026-10-16", "type": "CALL", "underlying": "SPY", "strike": 600, "spec_source": "SYNTHETIC", "known_utc": "2026-09-01T00:00:00Z"}
SESSION = {"open_utc": "2026-09-04T13:30:00Z", "close_utc": "2026-09-04T20:00:00Z", "available_utc": "2026-01-01T00:00:00Z", "source": "TEST_SESSION_FIXTURE"}


def quote(sec=2, size=1, bid=1.0, ask=1.1):
    t = f"2026-09-04T15:00:{sec:02d}Z"
    return {"contract_id": C["contract_id"], "source": "SYNTHETIC_TEST", "feed_type": "OPRA", "delayed": False,
            "bid": bid, "ask": ask, "bid_size": size, "ask_size": size, "size_units": "CONTRACTS", "observed_utc": t, "available_utc": t}


def test_fill_needs_post_decision_quote_and_honours_limit_size():
    kwargs = dict(side="BUY", limit_price=1.2, quantity=2, submitted_utc=T, execution_utc="2026-09-04T15:00:02Z")
    assert simulate_fill(quote(0), **kwargs)["reason"] == "no_post_submission_quote"
    assert simulate_fill(quote(), **kwargs)["status"] == "PARTIAL_FILL"
    assert simulate_fill(quote(ask=1.3), **kwargs)["reason"] == "not_marketable"
    assert simulate_fill({**quote(), "feed_type": "INDICATIVE"}, **kwargs)["status"] == "NO_FILL"


def test_ledger_cash_reservations_partial_fills_restart_and_idempotence():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "paper.sqlite"
        with PaperLedger(path) as ledger:
            ledger.initialize(20000, T)
            order = dict(at=T, contract=C, side="BUY", quantity=2, limit_price=1.2, session=SESSION, pick_id="frozen-fixture")
            ledger.submit("buy", **order)
            assert ledger.submit("buy", **order)["status"] == "DUPLICATE"
            assert ledger.snapshot(T)["reserved_cash"] == 241.6
            result = ledger.observe(quote(), at="2026-09-04T15:00:02Z")
            assert result["fills"][0]["quantity"] == 1
            assert ledger.observe(quote(), at="2026-09-04T15:00:03Z")["fills"] == []
        with PaperLedger(path) as ledger:
            assert ledger.snapshot("2026-09-04T15:00:03Z")["cash"] == 19889.2
            ledger.observe(quote(4), at="2026-09-04T15:00:04Z")
            assert ledger.snapshot("2026-09-04T15:00:04Z")["reserved_cash"] == 0
            ledger.submit("sell", at="2026-09-04T15:00:05Z", contract=C, side="SELL", quantity=2, limit_price=.9, session=SESSION, pick_id="frozen-fixture")
            ledger.observe(quote(6, size=2), at="2026-09-04T15:00:06Z")
            snap = ledger.snapshot("2026-09-04T15:00:06Z")
            assert not snap["positions"] and snap["realized_pnl"] == -23.2
            assert snap["cash"] == 19976.8


def test_small_account_does_not_relax_risk_and_bad_quantity_is_rejected():
    with TemporaryDirectory() as tmp, PaperLedger(Path(tmp) / "p.sqlite") as ledger:
        ledger.initialize(1000, T)
        for qty in (1, 0, True, 1.5):
            try:
                ledger.submit("bad", at=T, contract=C, side="BUY", quantity=qty, limit_price=1.1, session=SESSION, pick_id="x")
            except ValueError:
                pass
            else:
                assert False, qty
        assert ledger.snapshot(T)["cash"] == 1000


def test_corrupt_ledger_fails_closed_and_no_historical_current_state():
    with TemporaryDirectory() as tmp, PaperLedger(Path(tmp) / "p.sqlite") as ledger:
        ledger.initialize(1000, T)
        try:
            ledger.snapshot("2020-01-01T00:00:00Z")
        except ValueError:
            pass
        else:
            assert False
        ledger.db.execute("UPDATE events SET state='{}'")
        try:
            ledger.snapshot(T)
        except ValueError:
            pass
        else:
            assert False


def test_pending_orders_cannot_bypass_per_contract_risk_limit():
    with TemporaryDirectory() as tmp, PaperLedger(Path(tmp) / "p.sqlite") as ledger:
        ledger.initialize(10000, T)
        kw = dict(at=T, contract=C, side="BUY", quantity=1, limit_price=1.1, session=SESSION, pick_id="x")
        ledger.submit("first", **kw)
        try:
            ledger.submit("second", **kw)
        except ValueError:
            pass
        else:
            assert False, "two orders breached the combined 2 percent cap"
