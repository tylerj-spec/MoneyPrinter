#!/usr/bin/env python3
"""Create a local, allowlisted diagnostic ZIP. No raw data, keys, paths or automatic upload."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import zipfile
from app_paths import get_paths
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "claude/app/mp_v01/src"))
from localdata.archive import inventory
from localdata.providers import PROVIDERS
from strategy.picks import verify


def build(root: Path, destination: Path) -> Path:
    report = inventory(root / "external")
    counts = Counter()
    for item in report["datasets"]:
        name = item["provider"] if item["provider"] in PROVIDERS else "manual_or_other"
        counts[name] += 1
    picks, rejected = Counter(), 0
    for path in (root / "picks").glob("picks_*.json"):
        try:
            doc = json.loads(path.read_text("utf-8"))
            if not verify(doc):
                raise ValueError("invalid record")
            for pick in doc["picks"]:
                action = pick.get("action")
                picks[action if action in {"ABSTAIN", "PAPER_LONG_CALL", "PAPER_LONG_PUT"} else "other"] += 1
        except (ValueError, OSError, KeyError, TypeError):
            rejected += 1
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        sha = ""
    sha = sha if re.fullmatch("[a-f0-9]{40}", sha) else "UNAVAILABLE"
    payload = {"schema": "moneyprinter.feedback.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
               "python": platform.python_version(), "os_family": platform.system(), "code_commit": sha,
               "external_dataset_counts": dict(counts), "invalid_archives": len(report["errors"]),
               "pick_action_counts": dict(picks), "rejected_pick_files": rejected,
               "test_status": "NOT_INFERRED_FROM_COUNTS", "no_files_uploaded": True}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as out:
        out.writestr("diagnostics.json", json.dumps(payload, indent=2))
        out.writestr("README.txt", "Review before sharing. This bundle contains version and counts only.\nIt excludes raw data, quotes, settings, credentials, contact details and local paths.\nFor strategy refinement, separately review/share the export_research.py outputs.\n")
    return destination


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    root = get_paths().root
    out = a.out or root / "feedback" / ("feedback_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".zip")
    try:
        print("Created locally: " + str(build(root, out)))
        print("Open and review the ZIP before sharing. Nothing was uploaded.")
        return 0
    except (OSError, ValueError):
        print("Could not create feedback bundle; check destination and permissions.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
