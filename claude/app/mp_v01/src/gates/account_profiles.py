"""
Account-size profiles.

Added after Tyler specified a $1,000 initial Robinhood allocation (2026-08-12).

There is a hard arithmetic conflict between small accounts and prudent options
position sizing, and it is better to surface it in code than to discover it
after funding. See small_account_feasibility() below - the numbers are computed,
not asserted.
"""
from __future__ import annotations

from dataclasses import dataclass
from .risk import RiskLimits


@dataclass(frozen=True)
class AccountProfile:
    name: str
    equity_usd: float
    limits: RiskLimits
    notes: str


# Institutional-style defaults. These are what the risk literature supports,
# and they are NOT achievable at $1,000 with options - see below.
STANDARD = AccountProfile(
    name="standard",
    equity_usd=25_000,
    limits=RiskLimits(),          # 2% position, 6% heat, 5 positions
    notes="Default limits are feasible at this size.",
)

# What $1,000 actually permits. Concentration is forced, not chosen.
SMALL_ACCOUNT = AccountProfile(
    name="small_account_1k",
    equity_usd=1_000,
    limits=RiskLimits(
        max_position_pct=0.10,        # forced up from 2% - see feasibility report
        max_portfolio_heat_pct=0.20,  # forced up from 6%
        max_open_positions=2,         # cannot diversify meaningfully
        min_edge_after_costs=0.05,    # RAISED: costs eat ~10% round trip, so the
                                      # bar for taking a trade must be higher, not
                                      # lower, than at scale
        require_defined_risk=True,
    ),
    notes=(
        "Limits deliberately relaxed on sizing and TIGHTENED on required edge. "
        "A $1,000 options account cannot satisfy 2%/6% limits and must accept "
        "concentration. The compensating control is refusing more trades."
    ),
)


def small_account_feasibility(
    equity_usd: float = 1_000.0,
    *,
    option_mid_price: float = 1.15,
    contracts: int = 1,
    round_trip_cost_pct: float = 0.101,   # from the demo's 1.05/1.25 quote
    standard_max_position_pct: float = 0.02,
) -> dict:
    """
    Compute whether standard position limits are achievable at a given equity.

    Returns plain numbers so the conclusion can be checked rather than believed.
    """
    contract_cost = option_mid_price * 100 * contracts
    standard_budget = equity_usd * standard_max_position_pct
    pct_of_account = contract_cost / equity_usd
    round_trip_dollars = contract_cost * round_trip_cost_pct
    cost_as_pct_of_account = round_trip_dollars / equity_usd
    max_positions_at_standard = int(equity_usd * 0.06 / contract_cost) if contract_cost else 0

    return {
        "equity_usd": equity_usd,
        "one_contract_cost_usd": round(contract_cost, 2),
        "standard_2pct_budget_usd": round(standard_budget, 2),
        "can_afford_one_contract_within_2pct": contract_cost <= standard_budget,
        "one_contract_as_pct_of_account": round(pct_of_account, 4),
        "round_trip_cost_usd": round(round_trip_dollars, 2),
        "round_trip_cost_as_pct_of_account": round(cost_as_pct_of_account, 4),
        "max_positions_within_6pct_heat": max_positions_at_standard,
        "verdict": (
            "STANDARD_LIMITS_INFEASIBLE" if contract_cost > standard_budget
            else "STANDARD_LIMITS_FEASIBLE"
        ),
    }


if __name__ == "__main__":
    import json
    for eq in (1_000, 5_000, 25_000, 100_000):
        print(json.dumps(small_account_feasibility(eq), indent=2))
        print()
