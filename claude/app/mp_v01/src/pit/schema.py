"""
Point-in-time evidence record schema.

Implements the Core Record Contract: every piece of evidence carries the four
timestamps required to answer "what could we legitimately have known at time T?"

    event_time      when the thing happened in the world
    published_time  when a source first published it
    available_time  when WE could actually have consumed it (feed latency, paywall,
                    crawl delay). THIS is the only timestamp a backtest may filter on.
    ingested_time   when our pipeline actually stored it

Rule: a simulated decision at time T may see a record only if available_time <= T.
Filtering on event_time or published_time is lookahead and is rejected by the store.

Missing values are marked UNKNOWN. Nothing is ever invented.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


UNKNOWN = "UNKNOWN"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    QUARANTINED = "QUARANTINED"
    UNVERIFIED = "UNVERIFIED"


class SourceTier(str, Enum):
    """Reliability tier. Drives evidence weight; never overrides a risk gate."""
    PRIMARY_FILING = "PRIMARY_FILING"        # SEC/EDGAR, exchange, company IR
    EXCHANGE_DATA = "EXCHANGE_DATA"          # quotes, trades, chains
    MAJOR_PRESS = "MAJOR_PRESS"              # wire services
    SECONDARY_PRESS = "SECONDARY_PRESS"      # aggregators, syndicated
    SOCIAL_UNVERIFIED = "SOCIAL_UNVERIFIED"  # forums, X/Twitter, WSB
    UNKNOWN_TIER = "UNKNOWN"


def utc(ts: str | datetime) -> datetime:
    """Parse to a timezone-aware UTC datetime. Naive input is rejected loudly."""
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Naive datetime not allowed (ambiguous timezone): {ts!r}")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class EvidenceRecord:
    """One immutable observation. Revisions create NEW records, never mutate."""

    record_id: str
    entity_id: str
    ticker_at_time: str
    source_id: str
    source_tier: SourceTier
    claim: str

    event_time: datetime
    published_time: datetime
    available_time: datetime
    ingested_time: datetime

    # Lineage. Syndicated copies of one story share a lineage_cluster_id and
    # therefore count as ONE information event, not N confirmations.
    lineage_cluster_id: str
    original_source_id: str

    # Revision vintages. Originals are preserved; corrections supersede.
    revision_id: int = 0
    supersedes_record_id: str | None = None

    raw_content_hash: str = UNKNOWN
    parser_version: str = UNKNOWN
    license_classification: str = UNKNOWN
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED
    quarantine_reason: str | None = None

    numeric_value: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("event_time", "published_time", "available_time", "ingested_time"):
            v = getattr(self, name)
            if not isinstance(v, datetime) or v.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware datetime, got {v!r}")

        # Causality: you cannot publish before the event, nor consume before publish.
        if self.published_time < self.event_time:
            raise ValueError(
                f"published_time {self.published_time} precedes event_time "
                f"{self.event_time} for {self.record_id} - source timestamps are untrustworthy"
            )
        if self.available_time < self.published_time:
            raise ValueError(
                f"available_time {self.available_time} precedes published_time "
                f"{self.published_time} for {self.record_id} - this would grant hindsight"
            )

    def content_hash(self) -> str:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
            elif isinstance(v, Enum):
                d[k] = v.value
        return hashlib.sha256(
            json.dumps(d, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]


def make_record(**kw: Any) -> EvidenceRecord:
    """Convenience constructor that coerces ISO strings to UTC datetimes."""
    for f_ in ("event_time", "published_time", "available_time", "ingested_time"):
        if f_ in kw:
            kw[f_] = utc(kw[f_])
    if "ingested_time" not in kw and "available_time" in kw:
        kw["ingested_time"] = kw["available_time"]
    return EvidenceRecord(**kw)
