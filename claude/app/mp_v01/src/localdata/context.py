"""Already-collected context is visible only after receipt; no automatic weight changes."""
from __future__ import annotations
from datetime import timedelta
from pathlib import Path
from common.validation import digest, utc
from localdata.archive import inventory, read_dataset


def context_at(root: Path, cutoff_utc: str) -> dict:
    report = inventory(root, cutoff_utc=cutoff_utc)
    latest = {}
    for item in report["datasets"]:
        key = (item["provider"], item["scope"])
        if key not in latest or utc(item["available_utc"]) > utc(latest[key]["available_utc"]):
            latest[key] = item
    sources, events = [], []
    cutoff = utc(cutoff_utc)
    for item in latest.values():
        sources.append({k: item[k] for k in ("provider", "scope", "source", "dataset_id", "available_utc", "record_count", "files", "provenance")})
        if item["provider"] == "bls_calendar":
            _, records = read_dataset(Path(root) / "bls_calendar" / item["dataset_id"])
            for event in records:
                if (event.get("event_utc") and event.get("status") != "CANCELLED"
                        and cutoff <= utc(event["event_utc"]) <= cutoff + timedelta(days=10)):
                    events.append(event)
    result = {"decision_cutoff_utc": cutoff_utc, "datasets": sources,
              "upcoming_known_bls_events_10_calendar_days": events,
              "rejected_archives": len(report["errors"]),
              "used_in_score": False, "event_coverage": "INCOMPLETE",
              "note": "Context only; no calendar entry is not proof of no event. New sources do not change weights."}
    result["context_sha256"] = digest(result)
    return result
