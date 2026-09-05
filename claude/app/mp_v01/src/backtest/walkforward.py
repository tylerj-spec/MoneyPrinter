"""
Walk-forward evaluation with leakage detection.

A single in-sample backtest proves nothing. This module enforces:
  - chronological, non-overlapping train/test splits (never random shuffling)
  - a purge gap between train and test so the label horizon cannot bleed across
  - an embargo after each test window
  - an explicit assertion that no test-window timestamp precedes its train window

THE PURGE IS COUNTED IN TRADING SESSIONS, NOT CALENDAR DAYS.

That distinction is the whole reason `TradingCalendar` exists. The label
contract's horizon is five TRADING days, and no amount of calendar arithmetic
can count those. Thanksgiving week 2024 is the cheapest demonstration:

    train_end 2024-11-27 (Wed)   test_start 2024-12-02 (Mon)
    calendar gap  : 5 days       -> the old guard passed this
    session gap   : 1 session    -> only Fri the 29th; the 28th was a holiday
    a label decided 2024-11-27 resolves 2024-12-05,
    which is THREE SESSIONS INSIDE the test window

The previous version of this module counted `(test_start - train_end).days` and
so certified that split as safe. Worse, its own test asserted the calendar count
was correct, which is why a green suite reported no problem for three weeks. A
guard and the test that proves the guard works cannot share an assumption.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Sequence

from common.timezones import US_EASTERN as NY


class LeakageError(RuntimeError):
    pass


def as_session_date(value: date | datetime | str) -> date:
    """The market date a session-like value falls on.

    A tz-aware datetime is converted to US-Eastern before its date is taken.
    Reading the UTC date instead would move any decision time after 19:00 ET
    onto the following session — 2024-11-27T20:00-05:00 is 2024-11-28 in UTC,
    a day the market was shut.

    A naive datetime is taken at face value. Guessing a zone for it would be
    inference, and this file exists to stop inference passing as measurement.
    """
    if isinstance(value, datetime):          # datetime is a subclass of date
        return value.astimezone(NY).date() if value.tzinfo is not None else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"cannot read a session date from {type(value).__name__}: {value!r}")


@dataclass(frozen=True)
class TradingCalendar:
    """The sessions that actually happened, in order.

    There is no holiday table in this repository and adding one would be a
    fabrication of exactly the kind the project exists to prevent — a hand-typed
    list of closures is an assumption wearing the costume of data, and it goes
    stale silently. The only honest answer to "was the market open that day" is
    the set of bars that exist, so that is what this is built from: pass the
    dates of the bars you actually have.

        cal = TradingCalendar.from_dates(r["date"] for r in bars)

    A consequence worth stating plainly: a gap in your data looks exactly like a
    market holiday to this class, and it will happily purge across it. That
    makes the purge conservative (it drops more real sessions than it needs to),
    which is the safe direction, but it means the calendar is only as complete
    as the bars behind it.
    """
    sessions: tuple[date, ...]

    def __post_init__(self) -> None:
        if not self.sessions:
            raise ValueError("A trading calendar needs at least one session")
        if list(self.sessions) != sorted(set(self.sessions)):
            raise ValueError("sessions must be unique and in ascending order")

    @classmethod
    def from_dates(cls, values: Iterable[date | datetime | str]) -> "TradingCalendar":
        return cls(tuple(sorted({as_session_date(v) for v in values})))

    def __len__(self) -> int:
        return len(self.sessions)

    def __getitem__(self, i: int) -> date:
        return self.sessions[i]

    @property
    def first(self) -> date:
        return self.sessions[0]

    @property
    def last(self) -> date:
        return self.sessions[-1]

    def index_of(self, value: date | datetime | str) -> int:
        """Position of an exact session. Raises if that day was not a session."""
        d = as_session_date(value)
        i = bisect_left(self.sessions, d)
        if i == len(self.sessions) or self.sessions[i] != d:
            raise LeakageError(
                f"{d} is not a session in this calendar "
                f"({self.first}..{self.last}, {len(self)} sessions). "
                f"Either the market was shut that day or the bar is missing; "
                f"this class cannot tell those apart and will not guess.")
        return i

    def sessions_strictly_between(self, start: date | datetime | str,
                                  end: date | datetime | str) -> int:
        """How many sessions fall in the OPEN interval (start, end).

        Endpoints need not themselves be sessions. When they are, this is
        `index_of(end) - index_of(start) - 1`. Callers check ordering before
        calling, so an inverted interval returns a non-positive count rather
        than being silently clamped to zero.
        """
        a, b = as_session_date(start), as_session_date(end)
        return bisect_left(self.sessions, b) - bisect_right(self.sessions, a)

    def spans(self, start: date | datetime | str, end: date | datetime | str) -> bool:
        """True when both endpoints lie inside the calendar's own range.

        Outside it, `sessions_strictly_between` counts sessions this calendar
        has never heard of as zero, which reads as a violation for the wrong
        reason. Callers check this so the error can say so.
        """
        return self.first <= as_session_date(start) and as_session_date(end) <= self.last


@dataclass(frozen=True)
class Split:
    """One walk-forward split, addressed by session date.

    The four boundaries are normalised to market dates on construction, so a
    caller may pass datetimes, dates or ISO strings and get consistent
    comparisons out. `validate` is where the purge rule actually lives.
    """
    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        for field in ("train_start", "train_end", "test_start", "test_end"):
            object.__setattr__(self, field, as_session_date(getattr(self, field)))

    def validate(self, label_horizon_sessions: int, calendar: TradingCalendar) -> None:
        """Reject a split whose training labels resolve inside the test window.

        `calendar` is required, and deliberately so. The horizon is measured in
        trading days; without the sessions there is no way to count them, and a
        guard that cannot count what it claims to check should refuse rather
        than approximate. Passing no calendar is a TypeError at the call site,
        which is the earliest and loudest place to learn about it.

        THE RULE. A label decided on session `i` resolves at session `i + H`.
        The test window may therefore open no earlier than session `i + H + 1`,
        which is the same as requiring H whole sessions strictly between the
        last training session and the first test session. Opening ON `i + H` is
        already a leak: that session's close determines the training label's
        outcome, and it is not known at the 15:45 ET decision on that day.
        """
        if self.train_end >= self.test_start:
            raise LeakageError(
                f"Split {self.index}: train_end {self.train_end} overlaps "
                f"test_start {self.test_start}")
        if self.test_end <= self.test_start:
            raise LeakageError(f"Split {self.index}: empty test window")
        if not calendar.spans(self.train_end, self.test_start):
            raise LeakageError(
                f"Split {self.index}: {self.train_end}..{self.test_start} falls "
                f"outside the calendar ({calendar.first}..{calendar.last}). The "
                f"sessions in that gap are unknown, so the purge cannot be "
                f"verified — supply a calendar covering the split.")
        gap = calendar.sessions_strictly_between(self.train_end, self.test_start)
        if gap < label_horizon_sessions:
            calendar_days = (self.test_start - self.train_end).days
            raise LeakageError(
                f"Split {self.index}: purge gap {gap} session(s) < label horizon "
                f"{label_horizon_sessions} session(s). "
                f"{self.train_end} -> {self.test_start} is {calendar_days} "
                f"calendar day(s) but only {gap} of them were sessions, so a "
                f"label decided on {self.train_end} resolves at or after the "
                f"test window opens, leaking the future into training.")


def make_splits(
    calendar: TradingCalendar,
    *,
    train_sessions: int = 180,
    test_sessions: int = 30,
    label_horizon_sessions: int = 5,
    embargo_sessions: int = 2,
) -> list[Split]:
    """Rolling-origin splits laid out in session-index space.

    Every boundary is a real session by construction, which removes a second
    defect the calendar-arithmetic version had: it opened its first test window
    on 2024-07-04, a market holiday, having ended training on a Saturday.

    All four sizes are counts of SESSIONS, not calendar days. `train_sessions`
    of 180 is roughly nine calendar months, not six.
    """
    for name, value in (("train_sessions", train_sessions),
                        ("test_sessions", test_sessions)):
        if value < 1:
            raise ValueError(f"{name} must be >= 1, got {value}")
    if label_horizon_sessions < 0:
        raise ValueError(f"label_horizon_sessions must be >= 0, got {label_horizon_sessions}")
    if embargo_sessions < 0:
        raise ValueError(f"embargo_sessions must be >= 0, got {embargo_sessions}")

    splits: list[Split] = []
    cursor = 0
    i = 0
    last = len(calendar) - 1
    while True:
        tr_s = cursor
        tr_e = tr_s + train_sessions - 1
        # The purge drops exactly `label_horizon_sessions` sessions, so the
        # first test session sits H+1 sessions past the last training one.
        te_s = tr_e + label_horizon_sessions + 1
        te_e = te_s + test_sessions - 1
        if te_e > last:
            break
        s = Split(i, calendar[tr_s], calendar[tr_e], calendar[te_s], calendar[te_e])
        s.validate(label_horizon_sessions, calendar)
        splits.append(s)
        cursor += test_sessions + embargo_sessions
        i += 1
    if not splits:
        needed = train_sessions + label_horizon_sessions + test_sessions
        raise ValueError(
            f"Calendar too short for even one walk-forward split: "
            f"{len(calendar)} sessions, need at least {needed}")
    return splits


def assert_no_future_features(feature_times: Sequence[datetime],
                              decision_time: datetime) -> None:
    """Hard guard: every feature must be available at or before the decision."""
    bad = [t for t in feature_times if t > decision_time]
    if bad:
        raise LeakageError(
            f"{len(bad)} feature timestamp(s) postdate decision_time {decision_time}; "
            f"first offender {min(bad)}"
        )
