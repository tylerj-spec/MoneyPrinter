"""
The tests that matter most.

If these pass, the system cannot see the future. If any of these fail, every
backtest number the system ever produces is worthless, no matter how good it looks.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from harness import test, assert_raises, run_all
from pit.schema import make_record, SourceTier, ValidationStatus, EvidenceRecord
from pit.store import PointInTimeStore


def rec(rid, avail, *, event=None, pub=None, ticker="NVDA", cluster=None,
        supersedes=None, value=None, status=ValidationStatus.VALID, src="wire-1"):
    return make_record(
        record_id=rid, entity_id="NVDA-corp", ticker_at_time=ticker,
        source_id=src, source_tier=SourceTier.MAJOR_PRESS,
        claim=f"claim for {rid}",
        event_time=event or avail, published_time=pub or avail, available_time=avail,
        lineage_cluster_id=cluster or rid, original_source_id=src,
        supersedes_record_id=supersedes, numeric_value=value, validation_status=status,
    )


@test
def future_records_are_invisible():
    s = PointInTimeStore()
    s.add(rec("past", "2026-03-01T14:00:00Z"))
    s.add(rec("future", "2026-03-05T14:00:00Z"))
    ids = [r.record_id for r in s.as_of("2026-03-03T00:00:00Z")]
    assert ids == ["past"], ids


@test
def boundary_is_inclusive_and_exact_to_the_second():
    s = PointInTimeStore()
    s.add(rec("exact", "2026-03-01T14:00:00Z"))
    assert len(s.as_of("2026-03-01T13:59:59Z")) == 0, "visible one second too early"
    assert len(s.as_of("2026-03-01T14:00:00Z")) == 1, "not visible at its own timestamp"


@test
def publication_lag_is_respected():
    """Event happens 09:30, published 09:45, consumable 10:00. A 09:50 decision
    must not see it even though it was already published."""
    s = PointInTimeStore()
    s.add(rec("lagged", "2026-03-01T10:00:00Z",
              event="2026-03-01T09:30:00Z", pub="2026-03-01T09:45:00Z"))
    assert len(s.as_of("2026-03-01T09:50:00Z")) == 0
    assert len(s.as_of("2026-03-01T10:00:00Z")) == 1


@test
def impossible_timestamps_are_rejected_at_construction():
    # available before published would hand the model free hindsight
    assert_raises(ValueError, rec, "bad", "2026-03-01T09:00:00Z", pub="2026-03-01T10:00:00Z")
    # published before the event happened means the source clock is untrustworthy
    assert_raises(
        ValueError, make_record,
        record_id="bad2", entity_id="e", ticker_at_time="NVDA", source_id="s",
        source_tier=SourceTier.MAJOR_PRESS, claim="c",
        event_time="2026-03-02T00:00:00Z", published_time="2026-03-01T00:00:00Z",
        available_time="2026-03-03T00:00:00Z",
        lineage_cluster_id="c", original_source_id="s",
    )


@test
def naive_datetimes_are_rejected():
    assert_raises(ValueError, rec, "naive", "2026-03-01T14:00:00")


@test
def revision_does_not_leak_backwards():
    """A corrected figure must not appear in history before the correction existed.
    This is the classic macro-revision bug that silently inflates backtests."""
    s = PointInTimeStore()
    s.add(rec("gdp-v1", "2026-03-01T13:30:00Z", value=2.0, cluster="gdp-q1"))
    s.add(rec("gdp-v2", "2026-03-28T13:30:00Z", value=3.4, cluster="gdp-q1",
              supersedes="gdp-v1"))

    before = s.as_of("2026-03-10T00:00:00Z")
    assert len(before) == 1 and before[0].numeric_value == 2.0, \
        f"expected the ORIGINAL 2.0 print, got {[r.numeric_value for r in before]}"

    after = s.as_of("2026-04-01T00:00:00Z")
    assert len(after) == 1 and after[0].numeric_value == 3.4, \
        f"expected revised 3.4 after revision date, got {[r.numeric_value for r in after]}"


@test
def original_vintage_is_preserved_not_overwritten():
    s = PointInTimeStore()
    s.add(rec("v1", "2026-03-01T13:30:00Z", value=2.0, cluster="g"))
    s.add(rec("v2", "2026-03-28T13:30:00Z", value=3.4, cluster="g", supersedes="v1"))
    assert len(s) == 2, "revision must not destroy the original record"
    vals = sorted(r.numeric_value for r in s)
    assert vals == [2.0, 3.4], vals


@test
def revision_cannot_predate_what_it_supersedes():
    s = PointInTimeStore()
    s.add(rec("v1", "2026-03-28T13:30:00Z", value=2.0))
    assert_raises(ValueError, s.add,
                  rec("v2", "2026-03-01T13:30:00Z", value=3.4, supersedes="v1"))


@test
def syndicated_copies_count_as_one_information_event():
    """Nine outlets reprinting one wire story is one fact, not nine confirmations."""
    s = PointInTimeStore()
    for i in range(9):
        s.add(rec(f"copy{i}", "2026-03-01T14:00:00Z", cluster="wire-story-42",
                  src=f"outlet-{i}"))
    s.add(rec("independent", "2026-03-01T15:00:00Z", cluster="own-reporting",
              src="other-desk"))
    assert len(s.as_of("2026-03-01T16:00:00Z")) == 10, "all messages should be retrievable"
    assert s.independent_information_events("2026-03-01T16:00:00Z") == 2, \
        "must collapse to 2 distinct information events"


@test
def quarantined_records_excluded_by_default():
    s = PointInTimeStore()
    s.add(rec("clean", "2026-03-01T14:00:00Z"))
    s.add(rec("dirty", "2026-03-01T14:00:00Z", status=ValidationStatus.QUARANTINED))
    assert len(s.as_of("2026-03-01T15:00:00Z")) == 1
    assert len(s.as_of("2026-03-01T15:00:00Z", include_quarantined=True)) == 2


@test
def records_are_immutable():
    r = rec("frozen", "2026-03-01T14:00:00Z")
    try:
        r.numeric_value = 999.0
    except Exception:
        return
    raise AssertionError("EvidenceRecord must be frozen")


@test
def duplicate_record_ids_rejected():
    s = PointInTimeStore()
    s.add(rec("dup", "2026-03-01T14:00:00Z"))
    assert_raises(ValueError, s.add, rec("dup", "2026-03-02T14:00:00Z"))


@test
def no_api_exists_to_filter_on_event_time():
    """Defense in depth: if someone adds an event_time filter later, this fails."""
    import inspect
    sig = inspect.signature(PointInTimeStore.as_of)
    banned = {"event_time", "published_time", "ingested_time", "by_event_time"}
    assert not (banned & set(sig.parameters)), \
        f"as_of() must not expose non-available_time filters: {sig.parameters}"


@test
def unresolved_provenance_never_counts_as_corroboration():
    """False merges erase evidence; false splits invent it. Unknown lineage must
    count as zero corroboration, not as an independent confirmation."""
    from pit.store import independent_events_conservative
    s = PointInTimeStore()
    s.add(rec("known-a", "2026-03-01T10:00:00Z", cluster="story-1"))
    s.add(rec("known-b", "2026-03-01T11:00:00Z", cluster="story-2"))
    s.add(rec("murky",   "2026-03-01T12:00:00Z", cluster="UNKNOWN"))
    out = independent_events_conservative(s, "2026-03-01T13:00:00Z")
    assert out["confirmed_independent_events"] == 2, out
    assert out["unresolved_count"] == 1, out
    assert out["optimistic_upper_bound"] == 3, out
    assert "murky" in out["unresolved_provenance_records"]


if __name__ == "__main__":
    ok = run_all("NO-LOOKAHEAD / POINT-IN-TIME CORRECTNESS")
    sys.exit(0 if ok else 1)
