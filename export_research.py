#!/usr/bin/env python3
"""Export frozen decision inputs and separately computed paper outcomes as JSONL.

    python export_research.py

No network, no order placement, no fitting and no rewriting source records.
Inputs are whitelisted from the frozen record, never recomputed using today's
bars. Outcomes are a separate, timestamped research view of the existing
resolver, including its observed/modelled/mixed provenance and limitations.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from app_paths import get_paths

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "claude/app/mp_v01/src"))
from backtest.costs import CostModel
from pit.schema import utc
from strategy.picks import verify
from strategy.resolve import resolve_pick, DEFAULT_MARK_RATE
import excel_report as ex

INPUT_FIELDS = (
    "decision_date", "variant", "ticker", "action", "direction", "reason",
    "composite_score", "components_raw", "components_scaled", "weights", "contract",
    "exit_policy", "entry_fill_estimate", "fill_convention", "round_trip_cost_1x",
    "breakeven_move_pct", "selection_policy", "selection_metrics", "selection_audit",
    "gate_decision", "gate_failed", "edge_status",
)
OUTCOME_FIELDS = (
    "status", "exit_trigger", "exit_date", "days_held", "exit_price", "exit_mark_method",
    "exit_path_provenance", "exit_return_on_premium", "exit_pnl_per_contract",
    "horizon_date", "underlying_move_pct", "direction_correct", "target_excess_log_return",
    "label_contract_version", "horizon_return_on_premium", "horizon_mark_method", "detail",
)


def _dump(value) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _known_time(value, cutoff: datetime) -> bool:
    try:
        return utc(value) <= cutoff
    except (ValueError, TypeError, AttributeError):
        return False


def build_records(frozen: dict, bars: dict, chains: dict, evaluated_at: datetime,
                  costs: CostModel | None = None) -> tuple[list[dict], list[dict]]:
    """All-or-nothing export of one verified envelope. No input/outcome blending."""
    evaluated_at = utc(evaluated_at)
    _dump(frozen)  # No NaN/Infinity accepted, even if a legacy hash covers them.
    if not isinstance(frozen, dict) or not verify(frozen):
        raise ValueError("pick record failed integrity verification")
    if not frozen.get("record_sha256"):
        raise ValueError("legacy picks-only hash does not protect decision metadata; source preserved")
    if not _known_time(frozen.get("generated_utc"), evaluated_at):
        raise ValueError("generation timestamp missing, invalid or after evaluation")
    costs = costs or CostModel()
    known_bars = {
        ticker: [row for row in rows if _known_time(row.get("available_time"), evaluated_at)]
        for ticker, rows in bars.items()
    }
    inputs, outcomes = [], []
    for index, pick in enumerate(frozen["picks"]):
        if not isinstance(pick, dict):
            raise ValueError("pick is not an object")
        if pick.get("decision_date") != frozen.get("decision_date"):
            raise ValueError("pick decision date contradicts envelope")
        row_id = f"{frozen['record_sha256']}:{index}"
        inputs.append({
            "schema": "moneyprinter.research.inputs.v1", "row_id": row_id,
            "source_record_sha256": frozen["record_sha256"],
            "pick_contract_version": frozen.get("contract_version"),
            "generated_utc": frozen.get("generated_utc"),
            "prepared_inputs_sha256": frozen.get("source_files", {}).get("prepared_inputs_sha256"),
            "features": {key: pick.get(key) for key in INPUT_FIELDS},
        })
        result = {"status": "ABSTAIN"}
        if pick.get("action") != "ABSTAIN":
            ticker = pick.get("ticker")
            # Never bridge missing availability timestamps and call the result
            # an honest five-session path. Mark it unknown instead.
            relevant = [r for r in bars.get(ticker, [])
                        if str(r.get("date", "")) > str(pick.get("decision_date", ""))]
            missing_times = any(not r.get("available_time") for r in relevant)
            if missing_times:
                result = {"status": "UNKNOWN_DATA", "detail": "outcome bars lack availability timestamps"}
            else:
                known_chains = {day: doc for day, doc in chains.get(ticker, {}).items()
                                if _known_time(doc.get("available_time") or doc.get("snapshot_time_utc"),
                                               evaluated_at)}
                result = resolve_pick(pick, known_bars.get(ticker, []), known_chains, costs,
                                      benchmark_bars=known_bars.get("SPY"))
        outcomes.append({
            "schema": "moneyprinter.research.outcomes.v1", "row_id": row_id,
            # This is when THIS outcome view was produced, not an invented
            # historical label-availability timestamp.
            "evaluated_utc": evaluated_at.isoformat(),
            "outcome_available_utc": evaluated_at.isoformat(),
            "outcome_availability_basis": "CONSERVATIVE_EXPORT_TIME",
            "observed_quote_timing_verified": False,
            "cost_model": asdict(costs),
            "modelled_mark_assumptions": {"risk_free_rate": DEFAULT_MARK_RATE,
                "dividend_yield": 0.0, "volatility": "FIXED_ENTRY_IV", "model": "BLACK_SCHOLES"},
            "result": {key: result.get(key) for key in OUTCOME_FIELDS},
        })
    _dump(inputs)
    _dump(outcomes)
    return inputs, outcomes


def export(picks_dir: Path, data_dir: Path, out_dir: Path) -> tuple[Path, dict]:
    """Build one unique export directory. Repeated exports never overwrite one another."""
    if not picks_dir.is_dir():
        raise ValueError("picks directory does not exist")
    now = datetime.now(timezone.utc)
    bar_files = ex.find_bar_files(data_dir)
    bar_docs = {ticker: ex.load_bar_doc(path) for ticker, path in bar_files.items()}
    bars = {ticker: ex.dated_rows(doc) for ticker, doc in bar_docs.items()}
    chains = {ticker: ex.load_chains_by_date(data_dir, ticker) for ticker in bars}
    inputs, outcomes, sources, rejected, duplicates = [], [], [], [], []
    seen = set()
    for path in sorted(picks_dir.glob("picks_*.json")):
        try:
            raw = path.read_bytes()
            frozen = json.loads(raw)
            ins, outs = build_records(frozen, bars, chains, now)
            digest = frozen["record_sha256"]
            if digest in seen:
                duplicates.append(path.name)
                continue
            seen.add(digest)
            inputs.extend(ins)
            outcomes.extend(outs)
            sources.append({"file": path.name, "file_sha256": hashlib.sha256(raw).hexdigest(),
                            "record_sha256": digest})
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            rejected.append({"file": path.name, "reason": str(exc)})
    out_dir.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="research_" + now.strftime("%Y%m%dT%H%M%SZ_") , dir=out_dir))
    hashes = {}
    for name, rows in (("inputs.jsonl", inputs), ("outcomes.jsonl", outcomes)):
        content = "".join(_dump(row) + "\n" for row in rows).encode("utf-8")
        (target / name).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    manifest = {
        "schema": "moneyprinter.research.manifest.v1", "generated_utc": now.isoformat(),
        "input_count": len(inputs), "outcome_count": len(outcomes),
        "status_counts": dict(Counter(row["result"]["status"] for row in outcomes)),
        "path_provenance_counts": dict(Counter(row["result"].get("exit_path_provenance") or "UNRESOLVED"
                                                for row in outcomes)),
        "files_sha256": hashes, "pick_sources": sources,
        "outcome_bars_sha256": {ticker: hashlib.sha256(_dump(doc).encode()).hexdigest()
                                for ticker, doc in bar_docs.items()},
        "outcome_chains_sha256": hashlib.sha256(_dump(chains).encode()).hexdigest(),
        "rejected_sources": rejected, "duplicate_sources_skipped": duplicates,
        "limitations": [
            "Inputs and outcomes are separate; join on row_id only after chronological splitting.",
            "Outcomes inherit the existing resolver's assumptions; this is not a new options backtester.",
            "MODELLED_ONLY and MIXED paths must not be pooled with OBSERVED_ONLY as observed profits.",
            "Observed quotes are not verified fills; quote age and intraday exit timing remain unverified.",
            "Nearby decisions, variants and repeated contracts are correlated, not independent samples.",
            "No coefficients are fitted, no probabilities calibrated, and no live orders emitted.",
            "Legacy records with picks-only checksums remain untouched but are excluded from this export.",
        ],
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return target, manifest


def main(argv=None) -> int:
    paths = get_paths()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--picks-dir", default=str(paths.picks))
    parser.add_argument("--data-dir", default=str(paths.data))
    parser.add_argument("--out-dir", default=str(paths.root / "research"))
    args = parser.parse_args(argv)
    try:
        target, manifest = export(Path(args.picks_dir).expanduser(), Path(args.data_dir).expanduser(),
                                  Path(args.out_dir).expanduser())
    except (OSError, ValueError, TypeError) as exc:
        print(f"Research export failed: {exc}")
        return 1
    print(f"Research export: {target}")
    print(f"Inputs: {manifest['input_count']}; rejected files: {len(manifest['rejected_sources'])}")
    print("Paper research only. Read manifest.json before joining inputs to outcomes.")
    return 1 if manifest["rejected_sources"] or not manifest["input_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
