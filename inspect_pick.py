#!/usr/bin/env python3
"""Print a frozen pick's short justification, full indicators and source identities."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "claude/app/mp_v01/src"))
from strategy.picks import verify
from strategy.explain import attach_explanation, verify_explanation


def inspect(path: Path, index: int) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    if not verify(record):
        raise ValueError("Frozen record checksum failed; do not explain an edited record")
    picks = record["picks"]
    if index < 0 or index >= len(picks):
        raise ValueError(f"Pick index must be in 0..{len(picks)-1}")
    pick = picks[index]
    explanation = pick.get("explanation")
    if explanation is None:
        explanation = attach_explanation(pick, record.get("source_files"))["explanation"]
        return {"legacy_reconstructed_from_frozen_fields": True, "explanation": explanation}
    if not verify_explanation(explanation):
        raise ValueError("Explanation checksum failed")
    return {"legacy_reconstructed_from_frozen_fields": False, "explanation": explanation}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path)
    ap.add_argument("--pick", type=int, default=0, help="zero-based pick index, including abstentions")
    args = ap.parse_args(argv)
    try:
        result = inspect(args.file, args.pick)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}"); return 1
    print(result["explanation"]["short_justification"])
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
