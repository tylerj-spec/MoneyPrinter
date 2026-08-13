"""
Walk-forward evaluation with leakage detection.

A single in-sample backtest proves nothing. This module enforces:
  - chronological, non-overlapping train/test splits (never random shuffling)
  - a purge gap between train and test so the label horizon cannot bleed across
  - an embargo after each test window
  - an explicit assertion that no test-window timestamp precedes its train window
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


class LeakageError(RuntimeError):
    pass


@dataclass(frozen=True)
class Split:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    def validate(self, label_horizon_days: int) -> None:
        if self.train_end >= self.test_start:
            raise LeakageError(
                f"Split {self.index}: train_end {self.train_end} overlaps "
                f"test_start {self.test_start}"
            )
        gap = (self.test_start - self.train_end).days
        if gap < label_horizon_days:
            raise LeakageError(
                f"Split {self.index}: purge gap {gap}d < label horizon "
                f"{label_horizon_days}d. The last training labels resolve after "
                f"the test window opens, leaking the future into training."
            )
        if self.test_end <= self.test_start:
            raise LeakageError(f"Split {self.index}: empty test window")


def make_splits(
    start: datetime,
    end: datetime,
    *,
    train_days: int = 180,
    test_days: int = 30,
    label_horizon_days: int = 5,
    embargo_days: int = 2,
) -> list[Split]:
    """Rolling-origin splits. Purge gap == label horizon, plus an embargo."""
    splits: list[Split] = []
    i = 0
    cursor = start
    purge = timedelta(days=label_horizon_days)
    while True:
        tr_s = cursor
        tr_e = tr_s + timedelta(days=train_days)
        te_s = tr_e + purge
        te_e = te_s + timedelta(days=test_days)
        if te_e > end:
            break
        s = Split(i, tr_s, tr_e, te_s, te_e)
        s.validate(label_horizon_days)
        splits.append(s)
        cursor = cursor + timedelta(days=test_days + embargo_days)
        i += 1
    if not splits:
        raise ValueError("Date range too short for even one walk-forward split")
    return splits


def assert_no_future_features(feature_times: list[datetime], decision_time: datetime) -> None:
    """Hard guard: every feature must be available at or before the decision."""
    bad = [t for t in feature_times if t > decision_time]
    if bad:
        raise LeakageError(
            f"{len(bad)} feature timestamp(s) postdate decision_time {decision_time}; "
            f"first offender {min(bad)}"
        )
