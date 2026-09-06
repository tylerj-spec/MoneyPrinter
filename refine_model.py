#!/usr/bin/env python3
"""Register and evaluate a numerical challenger without changing active weights."""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
from app_paths import get_paths
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "claude/app/mp_v01/src"))
from common.validation import digest
from research.experiments import Experiment
from research.study import run_study
from strategy.picks import verify


def experiment(doc):
    return Experiment(**{**doc, "features": tuple(doc["features"]), "parameters": tuple(tuple(v) for v in doc.get("parameters", []))}).validate()


def demo():
    rng = random.Random(61)
    rows = []
    for i in range(360):
        d = date(2024, 1, 1) + timedelta(days=i)
        x = rng.uniform(-1, 1)
        positive = rng.random() < (.8 if x > 0 else .2)
        rows.append({"row_id": "SYNTHETIC-" + str(i), "ticker": "SYNTHETIC",
                     "decision_utc": d.isoformat() + "T15:00:00Z", "feature_available_utc": d.isoformat() + "T14:59:00Z",
                     "label_available_utc": (d + timedelta(days=1)).isoformat() + "T16:00:00Z",
                     "features": {"momentum_20d": x}, "net_return": .1 if positive else -.1,
                     "provenance": "SYNTHETIC_DEMO"})
    spec = Experiment("synthetic-smoke", "exercise a known artificial relationship; not trading evidence", "demo-1", ("momentum_20d",),
                      "2024-01-01", "2024-06-30", "2024-07-02", "2024-09-01", "2024-09-03", "2024-12-31")
    return spec, rows


def from_export(path: Path):
    manifest = json.loads((path / "manifest.json").read_text("utf-8"))
    for name in ("inputs.jsonl", "outcomes.jsonl"):
        if hashlib.sha256((path / name).read_bytes()).hexdigest() != manifest["files_sha256"][name]:
            raise ValueError("research export checksum mismatch")
    inputs = [json.loads(line) for line in (path / "inputs.jsonl").read_text("utf-8").splitlines() if line]
    outcomes = [json.loads(line) for line in (path / "outcomes.jsonl").read_text("utf-8").splitlines() if line]
    if len({o["row_id"] for o in outcomes}) != len(outcomes):
        raise ValueError("duplicate outcomes")
    by_id = {o["row_id"]: o for o in outcomes}
    rows = []
    for item in inputs:
        out = by_id.get(item["row_id"], {})
        result, f = out.get("result", {}), item["features"]
        observed = result.get("exit_path_provenance") == "OBSERVED_ONLY" and out.get("observed_quote_timing_verified") is True
        rows.append({"row_id": item["row_id"], "ticker": f.get("ticker"),
                     "decision_utc": item["generated_utc"], "feature_available_utc": item["generated_utc"],
                     "label_available_utc": out.get("outcome_available_utc"),
                     "features": {**(f.get("components_scaled") or {}), **(f.get("selection_metrics") or {}),
                                  **{k: (f.get("contract") or {}).get(k) for k in ("dte", "delta", "iv_solved", "relative_spread")}},
                     "net_return": result.get("exit_return_on_premium"),
                     "provenance": "OBSERVED_QUOTES" if observed else "UNVERIFIED_OR_MODELLED"})
    return rows


def from_replay(path: Path):
    dataset = json.loads((path / "dataset.json").read_text("utf-8"))
    report = json.loads((path / "results.json").read_text("utf-8"))
    if digest(dataset) != report["dataset_sha256"]:
        raise ValueError("replay dataset checksum mismatch")
    outcomes = {o["row_id"]: o for o in report["outcomes"]}
    if len(outcomes) != len(report["outcomes"]):
        raise ValueError("duplicate replay outcome ids")
    rows = []
    for file in sorted(path.glob("picks_replay_*.json")):
        record = json.loads(file.read_text("utf-8"))
        if not verify(record):
            raise ValueError("replay pick integrity failed")
        for i, p in enumerate(record["picks"]):
            row_id = record["record_sha256"] + ":" + str(i)
            o = outcomes[row_id]
            if o["status"] != "RESOLVED":
                continue
            if o["dataset_provenance"] != dataset["provenance"]:
                raise ValueError("replay provenance mismatch")
            rows.append({"row_id": row_id, "ticker": p["ticker"], "decision_utc": p["decision_utc"],
                         "feature_available_utc": record["source_files"]["decision_cutoff_utc"],
                         "label_available_utc": o["exit"]["available_utc"],
                         "features": {**p["components_scaled"], **p["selection_metrics"],
                                      **{k: p["contract"][k] for k in ("dte", "delta", "iv_solved", "relative_spread")}},
                         "net_return": o["return_on_premium"],
                         "provenance": "OBSERVED_QUOTES" if dataset["provenance"] == "USER_SUPPLIED_QUOTE_HISTORY" else "SYNTHETIC_DEMO"})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true")
    mode.add_argument("--register", type=Path, help="experiment specification JSON")
    mode.add_argument("--experiment", type=Path, help="previously registered record JSON")
    data = ap.add_mutually_exclusive_group()
    data.add_argument("--observations", type=Path, help="canonical research JSONL")
    data.add_argument("--research-export", type=Path)
    data.add_argument("--replay-dir", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc).isoformat()
    root = a.out or get_paths().root / "experiments"
    try:
        root.mkdir(parents=True, exist_ok=True)
        if a.register:
            spec = experiment(json.loads(a.register.read_text("utf-8")))
            record = {"specification": spec.record(), "registered_utc": now}
            record["registration_sha256"] = digest(record)
            file = root / (spec.record()["experiment_id"] + ".json")
            with file.open("x", encoding="utf-8") as output:
                json.dump(record, output, indent=2)
            print("Registered immutable experiment: " + str(file))
            return 0
        if a.demo:
            spec, rows = demo()
            registered = now
        else:
            record = json.loads(a.experiment.read_text("utf-8"))
            if record["registration_sha256"] != digest({k: v for k, v in record.items() if k != "registration_sha256"}):
                raise ValueError("experiment registration checksum mismatch")
            sd = {k: v for k, v in record["specification"].items() if k not in {"experiment_id", "model_version"}}
            spec, registered = experiment(sd), record["registered_utc"]
            if a.research_export:
                rows = from_export(a.research_export)
            elif a.replay_dir:
                rows = from_replay(a.replay_dir)
            elif a.observations:
                rows = [json.loads(line) for line in a.observations.read_text("utf-8").splitlines() if line]
            else:
                ap.error("choose --observations, --research-export or --replay-dir")
        report = run_study(spec, rows, registered_utc=registered, allow_synthetic=a.demo)
        report["data_sha256"] = digest(rows)
        target = Path(tempfile.mkdtemp(prefix="synthetic_" if a.demo else "trial_", dir=root))
        (target / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        print("Research report: " + str(target / "report.json"))
        print("Status: " + report["status"])
        print("No active strategy weights changed. No orders sent. Synthetic runs cannot qualify for promotion.")
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print("STUDY_REJECTED: " + str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
