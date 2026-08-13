"""
Label contract v1.0 - APPROVED by Tyler 2026-08-12 (SPEC-ROUND-003).

Target : binary sign of 5-trading-day forward LOG EXCESS total return vs SPY
Horizon: 5 trading days
Return : log total return, official close-to-close, t -> t+5
Clock  : decision at 15:45:00 America/New_York on day t.
         Features may use completed bars through t-1 plus intraday/event data
         with available_time <= 15:45 ET on t.
         The LABEL begins at the official t close (16:00).

The 15-minute gap is deliberate and load-bearing: the decision is made before
the closing print that the label is measured from, so the model cannot consume
the very price it is scored against.

For SPY itself, excess-vs-SPY is degenerate, so the target is the absolute
forward total-return sign.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import Enum

from common.timezones import US_EASTERN as NY

LABEL_CONTRACT_VERSION = "1.0.0"
HORIZON_TRADING_DAYS = 5
BENCHMARK = "SPY"
DECISION_TIME_ET = time(15, 45)


class LabelStatus(str, Enum):
    OK = "OK"
    CORPORATE_ACTION_UNRESOLVED = "CORPORATE_ACTION_UNRESOLVED"
    DELISTED_IN_HORIZON = "DELISTED_IN_HORIZON"
    INSUFFICIENT_FORWARD_BARS = "INSUFFICIENT_FORWARD_BARS"
    RETURN_GAP_UNRESOLVED = "RETURN_GAP_UNRESOLVED"  # a None sits inside an otherwise-long-enough window


@dataclass(frozen=True)
class Label:
    instrument_id: str
    decision_time_utc: datetime
    label_start_close_date: str
    horizon_trading_days: int
    y: int | None                 # 1, 0, or None when not OK
    excess_log_return: float | None
    status: LabelStatus
    contract_version: str = LABEL_CONTRACT_VERSION
    delisting_return_imputed: bool = False

    def is_usable(self) -> bool:
        return self.status == LabelStatus.OK and self.y is not None


def log_total_return(daily_returns: list[float]) -> float:
    """Compound daily total returns in log space.

    Uses RET (total return incl. distributions), NOT adjusted-price differences.
    Adjusted-price differencing silently rewrites history when a vendor restates
    its adjustment factors - the exact class of silent revision the project bans.
    """
    total = 0.0
    for r in daily_returns:
        if r is None:
            raise ValueError("None in return series; mark the label unresolved instead")
        if r <= -1.0:
            return float("-inf")   # total loss (e.g. -100% delisting)
        total += math.log1p(r)
    return total


def decision_time_utc_for(date_str: str) -> datetime:
    """15:45 ET on the given date, expressed in UTC.

    Uses the IANA tz database (via common.timezones) rather than a fixed
    offset, so this is correct on both sides of the March/November DST
    transitions instead of silently off by an hour half the year.
    """
    y, m, d = (int(x) for x in date_str.split("-"))
    return datetime(y, m, d, DECISION_TIME_ET.hour, DECISION_TIME_ET.minute,
                     tzinfo=NY).astimezone(timezone.utc)


def build_label(
    instrument_id: str,
    decision_date: str,
    instrument_forward_returns: list[float],
    benchmark_forward_returns: list[float],
    *,
    corporate_action_resolved: bool = True,
    delisted_in_horizon: bool = False,
    delisting_return: float | None = None,
) -> Label:
    """
    Construct one label. Fails closed: any unresolved condition yields y=None
    rather than a guess.
    """
    dt = decision_time_utc_for(decision_date)
    base = dict(
        instrument_id=instrument_id, decision_time_utc=dt,
        label_start_close_date=decision_date,
        horizon_trading_days=HORIZON_TRADING_DAYS,
    )

    if not corporate_action_resolved:
        return Label(**base, y=None, excess_log_return=None,
                     status=LabelStatus.CORPORATE_ACTION_UNRESOLVED)

    imputed = False
    inst = list(instrument_forward_returns)

    if delisted_in_horizon:
        if delisting_return is None:
            # No DLRET available -> assume total loss and flag the imputation.
            inst = inst + [-1.0]
            imputed = True
        else:
            if inst:
                inst[-1] = (1 + inst[-1]) * (1 + delisting_return) - 1
            else:
                inst = [delisting_return]

    if not delisted_in_horizon and len(inst) < HORIZON_TRADING_DAYS:
        return Label(**base, y=None, excess_log_return=None,
                     status=LabelStatus.INSUFFICIENT_FORWARD_BARS)
    if len(benchmark_forward_returns) < min(len(inst), HORIZON_TRADING_DAYS):
        return Label(**base, y=None, excess_log_return=None,
                     status=LabelStatus.INSUFFICIENT_FORWARD_BARS)

    # log_total_return() raises ValueError if a None sits inside the window
    # (a gap day that wasn't caught by the length checks above, e.g. a
    # NO_PRIOR_CLOSE bar in the middle of an otherwise sufficient series).
    # Fail closed with an unresolved label instead of letting that exception
    # escape and crash whatever is building labels in bulk.
    try:
        inst_lr = log_total_return(inst)
    except ValueError:
        return Label(**base, y=None, excess_log_return=None,
                     status=LabelStatus.RETURN_GAP_UNRESOLVED)

    if instrument_id == BENCHMARK:
        excess = inst_lr          # absolute sign for the benchmark itself
    else:
        try:
            bench_lr = log_total_return(benchmark_forward_returns[:len(inst)])
        except ValueError:
            return Label(**base, y=None, excess_log_return=None,
                         status=LabelStatus.RETURN_GAP_UNRESOLVED)
        excess = inst_lr - bench_lr

    status = LabelStatus.DELISTED_IN_HORIZON if delisted_in_horizon else LabelStatus.OK
    y = None if excess is None else int(excess > 0)
    if status == LabelStatus.DELISTED_IN_HORIZON:
        # Still a valid outcome - a delisting to zero is a real, scoreable result.
        status = LabelStatus.OK

    return Label(**base, y=y, excess_log_return=excess, status=status,
                 delisting_return_imputed=imputed)
