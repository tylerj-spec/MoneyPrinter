"""Shared strict validation for local research, timestamps and money inputs."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any


def number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, not a Boolean or string")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"{name} must be finite") from None
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return result


def whole(value: Any, name: str, *, minimum: int = 0) -> int:
    value = number(value, name, minimum=minimum)
    if not value.is_integer():
        raise ValueError(f"{name} must be a whole number")
    return int(value)


def utc(value: str | datetime, name: str = "timestamp") -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"{name} must be an ISO 8601 timestamp") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return result.astimezone(timezone.utc)


def iso(value: str | datetime) -> str:
    return utc(value).isoformat(timespec="microseconds")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()
