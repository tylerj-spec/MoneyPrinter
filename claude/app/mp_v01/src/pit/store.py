"""
Point-in-time evidence store.

The single job of this class is to make hindsight structurally impossible rather
than merely discouraged. Every read goes through as_of(decision_time), which
filters on available_time only.

Two failure modes this defends against:

1. Lookahead by timestamp. Filtering on event_time or published_time lets the
   backtest see a story before it could have been consumed. Only available_time
   is permitted, and there is no API to filter on anything else.

2. Silent revision leakage. If a macro print or fundamental is later corrected,
   a naive store returns the CORRECTED value for historical dates - which the
   model could never have seen. as_of() returns the vintage that was live at the
   decision time, and preserves the original.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Iterator

from .schema import EvidenceRecord, ValidationStatus, utc


class LookaheadError(RuntimeError):
    """Raised when an operation would expose information from the future."""


class PointInTimeStore:
    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []
        self._by_id: dict[str, EvidenceRecord] = {}
        self._superseded_by: dict[str, str] = {}

    def add(self, rec: EvidenceRecord) -> None:
        if rec.record_id in self._by_id:
            raise ValueError(f"Duplicate record_id {rec.record_id}; records are immutable")
        if rec.supersedes_record_id:
            prior = self._by_id.get(rec.supersedes_record_id)
            if prior is None:
                raise ValueError(
                    f"{rec.record_id} supersedes unknown record {rec.supersedes_record_id}"
                )
            if rec.available_time < prior.available_time:
                raise ValueError(
                    "A revision cannot become available before the value it supersedes"
                )
            # Two records superseding the SAME original leave no way to say which
            # vintage is current. The old code overwrote this entry, orphaning the
            # first revision so nothing marked it superseded and as_of() returned
            # BOTH as current - which then inflates
            # independent_information_events() and, through it, the evidence gate.
            # Resolving the ambiguity by guessing (say, latest available_time) would
            # be inference; rejecting it is not.
            already = self._superseded_by.get(rec.supersedes_record_id)
            if already is not None:
                raise ValueError(
                    f"{rec.record_id} supersedes {rec.supersedes_record_id}, but "
                    f"{already} already does. Two revisions of one record cannot "
                    f"both be current. Chain it instead: supersede {already}."
                )
            self._superseded_by[rec.supersedes_record_id] = rec.record_id
        self._records.append(rec)
        self._by_id[rec.record_id] = rec

    def add_all(self, recs: Iterable[EvidenceRecord]) -> None:
        for r in recs:
            self.add(r)

    def as_of(
        self,
        decision_time: str | datetime,
        *,
        ticker: str | None = None,
        include_quarantined: bool = False,
        latest_vintage_only: bool = True,
    ) -> list[EvidenceRecord]:
        """Everything legitimately knowable at decision_time. The ONLY read path."""
        t = utc(decision_time)
        out: list[EvidenceRecord] = []
        for r in self._records:
            if r.available_time > t:
                continue  # not yet consumable - the core no-hindsight filter
            if ticker and r.ticker_at_time != ticker:
                continue
            if not include_quarantined and r.validation_status == ValidationStatus.QUARANTINED:
                continue
            if latest_vintage_only:
                # Skip if a revision superseding this record was ALSO already
                # available at t. If the revision came later, this stale vintage
                # is exactly what we should return.
                sup_id = self._superseded_by.get(r.record_id)
                if sup_id is not None:
                    sup = self._by_id[sup_id]
                    if sup.available_time <= t:
                        continue
            out.append(r)
        out.sort(key=lambda r: r.available_time)
        return out

    def independent_information_events(
        self, decision_time: str | datetime, *, ticker: str | None = None
    ) -> int:
        """
        Count DISTINCT information events, not messages.

        Ten outlets syndicating one wire story is one event. Counting it as ten
        confirmations is how a system talks itself into false confidence.
        """
        recs = self.as_of(decision_time, ticker=ticker)
        return len({r.lineage_cluster_id for r in recs})

    def lineage_breakdown(
        self, decision_time: str | datetime, *, ticker: str | None = None
    ) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for r in self.as_of(decision_time, ticker=ticker):
            groups[r.lineage_cluster_id].append(r.record_id)
        return dict(groups)

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[EvidenceRecord]:
        return iter(self._records)


# ---------------------------------------------------------------------------
# Lineage-uncertainty handling.
#
# Added after BLUEPRINT-REVIEW-002 (data_lineage): collapsing syndicated copies
# assumes provenance is always resolvable. It is not.
#   - A FALSE MERGE erases genuinely independent corroboration.
#   - A FALSE SPLIT double-counts one story as two confirmations.
# Both corrupt the evidence-independence gate, in opposite directions.
#
# Records whose lineage is unresolved must therefore be counted CONSERVATIVELY:
# an unresolved record cannot contribute to the independent-evidence count, and
# its existence is reported so a human can adjudicate.
# ---------------------------------------------------------------------------

UNKNOWN_LINEAGE = "UNKNOWN"


def _is_unresolved(cluster_id: str | None) -> bool:
    return cluster_id is None or str(cluster_id).upper().startswith("UNKNOWN")


def independent_events_conservative(
    store: "PointInTimeStore",
    decision_time,
    *,
    ticker: str | None = None,
) -> dict:
    """
    Conservative evidence count with explicit uncertainty accounting.

    Returns confirmed_independent_events (safe to feed the risk gate),
    plus the unresolved set that a human must adjudicate.
    """
    recs = store.as_of(decision_time, ticker=ticker)
    resolved, unresolved = set(), []
    for r in recs:
        if _is_unresolved(r.lineage_cluster_id):
            unresolved.append(r.record_id)
        else:
            resolved.add(r.lineage_cluster_id)
    return {
        "confirmed_independent_events": len(resolved),
        "unresolved_provenance_records": unresolved,
        "unresolved_count": len(unresolved),
        # Upper bound if every unresolved record turned out to be independent.
        "optimistic_upper_bound": len(resolved) + len(unresolved),
        "note": (
            "Only confirmed_independent_events may be passed to the risk gate. "
            "Unresolved provenance is never counted as corroboration."
        ),
    }
