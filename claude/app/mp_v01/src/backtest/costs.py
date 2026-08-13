"""
Execution cost model.

A backtest that fills at the mid price is a fantasy generator. Options in
particular die on the spread: a 25-delta contract quoted 1.05/1.25 loses ~8% of
notional round-trip before the thesis is even tested.

Every number here is a MODELLING ASSUMPTION, not a measured fill. They must be
recalibrated against real fills during paper trading before any result is trusted.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    # Equities
    equity_commission_per_share: float = 0.0
    equity_slippage_bps: float = 1.0          # fraction of a spread crossed

    # Options
    option_commission_per_contract: float = 0.65   # typical retail; verify with broker
    option_exchange_fees_per_contract: float = 0.15
    spread_capture: float = 0.5   # 0.5 = pay half the quoted spread; 1.0 = full cross

    # Quote hygiene
    max_quote_age_seconds: int = 60
    max_relative_spread: float = 0.10   # reject if spread/mid exceeds this

    def equity_fill_price(self, mid: float, side: str, spread: float) -> float:
        direction = 1 if side.upper() == "BUY" else -1
        slip = (spread / 2) * self.spread_capture + mid * (self.equity_slippage_bps / 10_000)
        return mid + direction * slip

    def option_fill_price(self, bid: float, ask: float, side: str) -> float:
        if bid <= 0 or ask <= 0 or ask < bid:
            raise ValueError(f"Unusable quote bid={bid} ask={ask}")
        mid = (bid + ask) / 2
        half = (ask - bid) / 2
        direction = 1 if side.upper() == "BUY" else -1
        return round(mid + direction * half * self.spread_capture, 4)

    def option_round_trip_cost(self, bid: float, ask: float, contracts: int) -> float:
        entry = self.option_fill_price(bid, ask, "BUY")
        exit_ = self.option_fill_price(bid, ask, "SELL")
        spread_cost = (entry - exit_) * 100 * contracts
        fees = 2 * contracts * (
            self.option_commission_per_contract + self.option_exchange_fees_per_contract
        )
        return round(spread_cost + fees, 2)

    def quote_is_tradeable(self, bid: float, ask: float, age_seconds: float) -> tuple[bool, str]:
        if bid <= 0 or ask <= 0:
            return False, "non-positive quote"
        if ask < bid:
            return False, "crossed quote"
        if age_seconds > self.max_quote_age_seconds:
            return False, f"stale quote ({age_seconds:.0f}s > {self.max_quote_age_seconds}s)"
        mid = (bid + ask) / 2
        rel = (ask - bid) / mid
        if rel > self.max_relative_spread:
            return False, f"spread too wide ({rel:.1%} > {self.max_relative_spread:.0%})"
        return True, "ok"
