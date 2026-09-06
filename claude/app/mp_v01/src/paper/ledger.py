"""Local SQLite paper ledger: reservations, partial fills, fees and replayable events.

No network or broker client. Money is integer cents; option prices are dollars
per underlying unit. Hashes detect corruption, not malicious owner rewriting.
"""
from __future__ import annotations
import copy
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sqlite3
import json
from typing import Any
from common.validation import canonical, digest, iso, number, utc, whole
from gates.risk import RiskLimits
from paper.quotes import quote_identity, quote_quality, simulate_fill


def cents(value: float) -> int:
    number(value, "money")
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def premium_cents(price: float, quantity: int, multiplier: int = 100) -> int:
    number(price, "premium", minimum=0)
    whole(quantity, "quantity", minimum=1)
    whole(multiplier, "multiplier", minimum=1)
    return int((Decimal(str(price)) * quantity * multiplier * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class PaperPosition:
    position_id: str
    ticker: str
    contract_id: str
    quantity: int
    entry_price: float
    multiplier: int = 100

    def __post_init__(self):
        whole(self.quantity, "quantity", minimum=1)
        whole(self.multiplier, "multiplier", minimum=1)
        if number(self.entry_price, "entry_price", minimum=0) <= 0:
            raise ValueError("positive entry required")
        if not self.position_id or not self.contract_id or not self.ticker:
            raise ValueError("position and contract identities required")

    def max_loss(self) -> float:
        return premium_cents(self.entry_price, self.quantity, self.multiplier) / 100


@dataclass(frozen=True)
class PaperAccount:
    equity: float
    cash: float
    positions: tuple[PaperPosition, ...] = ()

    def __post_init__(self):
        if number(self.equity, "equity", minimum=0) <= 0:
            raise ValueError("positive equity required")
        number(self.cash, "cash", minimum=0)
        if len({p.position_id for p in self.positions}) != len(self.positions):
            raise ValueError("duplicate paper position id")

    def open_risk(self) -> float:
        return sum(premium_cents(p.entry_price, p.quantity, p.multiplier) for p in self.positions) / 100

    def snapshot(self) -> dict[str, Any]:
        return {"equity": self.equity, "cash": self.cash, "open_positions": len(self.positions),
                "open_risk": self.open_risk(), "positions": [asdict(p) for p in self.positions]}


def proposal_context(account: PaperAccount, *, entry_price: float, quantity: int = 1,
                     multiplier: int = 100) -> dict:
    proposed = premium_cents(number(entry_price, "entry_price", minimum=.000001), quantity, multiplier) / 100
    return {"position_pct": proposed / account.equity,
            "portfolio_heat_pct": (account.open_risk() + proposed) / account.equity,
            "open_positions": len(account.positions), "proposed_max_loss": proposed,
            "cash_sufficient": account.cash >= proposed}


def apply_long_fill(account: PaperAccount, position: PaperPosition) -> PaperAccount:
    if any(p.position_id == position.position_id for p in account.positions):
        raise ValueError("duplicate paper position id")
    cost = position.max_loss()
    if cents(cost) > cents(account.cash):
        raise ValueError("insufficient paper cash")
    return PaperAccount(account.equity, (cents(account.cash) - cents(cost)) / 100,
                        account.positions + (position,))


class PaperLedger:
    """Transactionally updated local simulation journal. Close before backup on Windows."""
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, command_id TEXT UNIQUE NOT NULL, at TEXT NOT NULL, request TEXT NOT NULL, state TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL)")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def _load(self) -> tuple[dict | None, str, str | None]:
        previous, state, last_at = "", None, None
        for seq, cid, at, request, encoded, prev, checksum in self.db.execute("SELECT * FROM events ORDER BY seq"):
            expected = digest({"seq": seq, "command_id": cid, "at": at, "request": request,
                               "state": encoded, "previous_hash": previous})
            if prev != previous or checksum != expected:
                raise ValueError("paper ledger integrity failed")
            state = json.loads(encoded)
            previous, last_at = checksum, at
        return state, previous, last_at

    def _change(self, command_id: str, at: str, request: dict, reducer) -> dict:
        at = iso(at)
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 256:
            raise ValueError("stable command id required")
        encoded_request = canonical(request).decode()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            state, previous, last_at = self._load()
            duplicate = self.db.execute("SELECT request FROM events WHERE command_id=?", (command_id,)).fetchone()
            if duplicate:
                if duplicate[0] != encoded_request:
                    raise ValueError("command id reused with different inputs")
                self.db.execute("COMMIT")
                return {"status": "DUPLICATE", "state": state}
            if last_at and utc(at) < utc(last_at):
                raise ValueError("paper event time cannot move backwards")
            new, result = reducer(copy.deepcopy(state))
            encoded_state = canonical(new).decode()
            seq = self.db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events").fetchone()[0]
            checksum = digest({"seq": seq, "command_id": command_id, "at": at,
                               "request": encoded_request, "state": encoded_state, "previous_hash": previous})
            self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                            (seq, command_id, at, encoded_request, encoded_state, previous, checksum))
            self.db.execute("COMMIT")
            return {**result, "state": new, "event_hash": checksum}
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def initialize(self, cash: float, at: str, *, fee_per_contract: float = .80) -> dict:
        initial = cents(number(cash, "cash", minimum=.01))
        fee = cents(number(fee_per_contract, "fee_per_contract", minimum=0))
        def init(state):
            if state is not None:
                raise ValueError("ledger already initialized")
            return {"schema": "moneyprinter.paper.v1", "cash_cents": initial,
                    "starting_cash_cents": initial, "fee_cents": fee, "realized_pnl_cents": 0,
                    "positions": {}, "orders": {}, "marks": {}, "consumed": {}}, {"status": "INITIALIZED"}
        return self._change("INITIALIZE", at, {"cash_cents": initial, "fee_cents": fee}, init)

    @staticmethod
    def _reserved(state):
        return sum(premium_cents(o["limit_price"], o["remaining"]) + o["remaining"] * state["fee_cents"]
                   for o in state["orders"].values() if o["side"] == "BUY" and o["remaining"] > 0)

    @staticmethod
    def _equity(state, at):
        equity = state["cash_cents"]
        for cid, position in state["positions"].items():
            q = state["marks"].get(cid)
            if not q or not quote_quality(q, decision_utc=at)[0]:
                return None
            equity += premium_cents(q["bid"], position["quantity"])
        return equity

    def snapshot(self, at: str) -> dict:
        state, checksum, last_at = self._load()
        if last_at and utc(at) < utc(last_at):
            raise ValueError("snapshot precedes latest event; use a separate historical replay ledger")
        if state is None:
            raise ValueError("initialize a paper account first")
        equity = self._equity(state, at)
        return {"schema": state["schema"], "as_of_utc": iso(at), "cash": state["cash_cents"] / 100,
                "reserved_cash": self._reserved(state) / 100,
                "liquidation_equity": None if equity is None else equity / 100,
                "liquidation_equity_basis": "bid marks before hypothetical exit commissions",
                "realized_pnl": state["realized_pnl_cents"] / 100,
                "positions": state["positions"], "orders": state["orders"], "journal_hash": checksum,
                "mode": "LOCAL_PAPER_SIMULATION_ONLY"}

    def submit(self, order_id: str, *, at: str, contract: dict, side: str, quantity: int,
               limit_price: float, session: dict, pick_id: str,
               limits: RiskLimits = RiskLimits()) -> dict:
        quantity = whole(quantity, "quantity", minimum=1)
        limit_price = number(limit_price, "limit_price", minimum=.000001)
        if side not in {"BUY", "SELL"} or not pick_id:
            raise ValueError("side and immutable pick id required")
        cid = contract.get("contract_id")
        if (not isinstance(cid, str) or not cid or contract.get("standard_contract") is not True
                or contract.get("premium_multiplier") != 100 or contract.get("deliverable_shares") != 100):
            raise ValueError("only explicitly verified standard 100-share contracts are supported")
        start, end, available = utc(session["open_utc"]), utc(session["close_utc"]), utc(session["available_utc"])
        if (not session.get("source") or available > utc(at) or not start <= utc(at) < end
                or start.weekday() >= 5 or start.date() != end.date()):
            raise ValueError("verified open session required at submission")
        dte = (date.fromisoformat(contract["expiration"]) - utc(at).date()).days
        if dte <= 0 or (side == "BUY" and not limits.min_dte <= dte <= limits.max_dte):
            raise ValueError("expiry-day trades and entries outside the DTE band are unsupported")
        if (contract.get("type") not in {"CALL", "PUT"} or not contract.get("underlying")
                or not contract.get("spec_source") or utc(contract["known_utc"]) > utc(at)
                or number(contract.get("strike"), "strike", minimum=0) <= 0):
            raise ValueError("complete point-in-time contract specifications required")
        request = {"contract": contract, "side": side, "quantity": quantity,
                   "limit_price": limit_price, "session": session, "pick_id": pick_id,
                   "risk_limits": asdict(limits)}
        def submit(state):
            if state is None:
                raise ValueError("initialize a paper account first")
            if order_id in state["orders"]:
                raise ValueError("order id already exists")
            if side == "BUY":
                cost = premium_cents(limit_price, quantity) + state["fee_cents"] * quantity
                if cost > state["cash_cents"] - self._reserved(state):
                    raise ValueError("insufficient unreserved paper cash")
                equity = self._equity(state, at)
                if equity is None or equity <= 0:
                    raise ValueError("fresh liquidation equity required for another entry")
                risk = sum(p["cost_cents"] for p in state["positions"].values()) + self._reserved(state)
                same_risk = state["positions"].get(cid, {}).get("cost_cents", 0) + sum(
                    premium_cents(o["limit_price"], o["remaining"]) + o["remaining"] * state["fee_cents"]
                    for o in state["orders"].values() if o["contract_id"] == cid and o["side"] == "BUY" and o["remaining"])
                if (same_risk + cost) / equity > limits.max_position_pct or (risk + cost) / equity > limits.max_portfolio_heat_pct:
                    raise ValueError("paper risk budget exceeded; limits are not auto-relaxed")
                exposures = set(state["positions"]) | {o["contract_id"] for o in state["orders"].values()
                                                       if o["side"] == "BUY" and o["remaining"]}
                if cid not in exposures and len(exposures) >= limits.max_open_positions:
                    raise ValueError("maximum open exposures reached")
            else:
                held = state["positions"].get(cid, {}).get("quantity", 0)
                reserved = sum(o["remaining"] for o in state["orders"].values()
                               if o["side"] == "SELL" and o["contract_id"] == cid)
                if quantity > held - reserved:
                    raise ValueError("cannot sell more than the unreserved long position")
            state["orders"][order_id] = {"contract_id": cid, "contract": contract,
                "side": side, "quantity": quantity, "remaining": quantity,
                "limit_price": limit_price, "submitted_utc": iso(at), "session": session,
                "pick_id": pick_id, "status": "PENDING_RESEARCH_SIMULATION"}
            return state, {"status": "SUBMITTED"}
        return self._change("order:" + order_id, at, request, submit)

    def observe(self, q: dict, *, at: str) -> dict:
        ident = quote_identity(q)
        def observe(state):
            if state is None:
                raise ValueError("initialize a paper account first")
            valid, reason = quote_quality(q, decision_utc=at)
            if not valid:
                return state, {"status": "REJECTED_QUOTE", "reason": reason, "fills": []}
            cid = q["contract_id"]
            state["marks"][cid] = q
            fills = []
            for oid, order in sorted(state["orders"].items(), key=lambda item: (item[1]["submitted_utc"], item[0])):
                if not order["remaining"] or order["contract_id"] != cid:
                    continue
                session = order["session"]
                if utc(at) >= utc(session["close_utc"]):
                    order.update(remaining=0, status="EXPIRED_DAY_ORDER")
                    continue
                if utc(at) < utc(session["open_utc"]):
                    continue
                key = ident + ":" + order["side"]
                fill = simulate_fill(q, side=order["side"], limit_price=order["limit_price"],
                    quantity=order["remaining"], submitted_utc=order["submitted_utc"], execution_utc=at,
                    consumed_size=state["consumed"].get(key, 0))
                if fill["status"] == "NO_FILL":
                    continue
                qty = fill["quantity"]
                money = premium_cents(fill["price"], qty)
                fee = qty * state["fee_cents"]
                if order["side"] == "BUY":
                    p = state["positions"].setdefault(cid, {"quantity": 0, "cost_cents": 0,
                                                          "contract": order["contract"]})
                    state["cash_cents"] -= money + fee
                    p["quantity"] += qty
                    p["cost_cents"] += money + fee
                else:
                    p = state["positions"][cid]
                    basis = p["cost_cents"] if qty == p["quantity"] else round(p["cost_cents"] * qty / p["quantity"])
                    if state["cash_cents"] + money < fee:
                        continue
                    state["cash_cents"] += money - fee
                    state["realized_pnl_cents"] += money - fee - basis
                    p["quantity"] -= qty
                    p["cost_cents"] -= basis
                    if not p["quantity"]:
                        del state["positions"][cid]
                state["consumed"][key] = state["consumed"].get(key, 0) + qty
                order["remaining"] -= qty
                order["status"] = "PARTIAL_FILL" if order["remaining"] else "FILLED"
                fills.append({**fill, "order_id": oid, "fee_cents": fee})
            return state, {"status": "OBSERVED", "fills": fills}
        return self._change("quote:" + ident + ":" + iso(at), at, {"quote": q}, observe)

    def cancel(self, order_id: str, *, at: str) -> dict:
        def cancel(state):
            if state is None or order_id not in state["orders"]:
                raise ValueError("unknown order")
            order = state["orders"][order_id]
            if order["remaining"]:
                order.update(remaining=0, status="CANCELLED")
            return state, {"status": "CANCELLED"}
        return self._change("cancel:" + order_id, at, {"order_id": order_id}, cancel)
