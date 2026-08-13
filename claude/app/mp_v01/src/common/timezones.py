"""
Shared US-Eastern timezone handling.

Every prior version of this codebase converted ET -> UTC with a hard-coded
ET_UTC_OFFSET_HOURS = 4. That is only correct while EDT (daylight time) is in
effect, roughly mid-March to early November. Outside that window (EST, UTC-5)
every available_time / decision_time / event_time computed with the old
constant is off by exactly one hour - a silent correctness bug in the same
family the rest of this project exists to prevent, not a cosmetic issue.

This module uses the IANA tz database via the stdlib `zoneinfo` module so ET
math is correct across DST transitions automatically.

WINDOWS NOTE: zoneinfo needs an IANA tz database. Linux and macOS normally
ship one system-wide; Windows does not, prior to Python bundling its own.
If this raises ZoneInfoNotFoundError, run:  pip install tzdata
"""
from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    US_EASTERN = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError as e:  # pragma: no cover - depends on host tz database
    raise RuntimeError(
        "Could not load the 'America/New_York' timezone database. "
        "On Windows this usually means the tzdata package is missing. Fix with:\n"
        "    pip install tzdata"
    ) from e
