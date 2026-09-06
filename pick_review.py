#!/usr/bin/env python3
"""Offline pick review with short justification, indicators and exact input drill-down."""
from __future__ import annotations
import argparse
import html
import json
import re
from pathlib import Path
import sys
from app_paths import get_paths
sys.path.insert(0, str(Path(__file__).resolve().parent / "claude/app/mp_v01/src"))
from common.validation import digest
from strategy.explain import attach_explanation, verify_explanation
from strategy.picks import verify

CSS = """
:root { color-scheme: dark; --bg:#171a21; --panel:#232833; --text:#edf0f7; --muted:#b5bfd0; }
body { background:var(--bg); color:var(--text); font:16px/1.55 system-ui,sans-serif; margin:0; }
main { max-width:1100px; padding:28px; margin:auto; } h1 { margin:0; }
article { background:var(--panel); padding:20px; margin:20px 0; border:1px solid #718096; border-radius:10px; }
a { color:inherit; } .note { color:var(--muted); } summary { cursor:pointer; font-weight:600; padding:10px 0; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:13px; }
table { border-collapse:collapse; width:100%; font-size:14px; } td,th { text-align:left; padding:8px; border-bottom:1px solid #718096; }
.light { color-scheme:light; --bg:#f4f6fa; --panel:#fff; --text:#18212f; --muted:#4e5c72; }
button { padding:8px 14px; cursor:pointer; } .scroll { overflow:auto; }
"""


def esc(value) -> str:
    return html.escape(str(value) if value is not None else "UNKNOWN")


def input_name(record):
    name = record.get("source_files", {}).get("decision_inputs_file", "")
    return name if isinstance(name, str) and re.fullmatch(r"inputs_[a-f0-9]{64}\.json", name) else None


def render(record: dict, source: str) -> str:
    if not verify(record):
        raise ValueError("Pick record integrity failed")
    chunks = ["<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>",
              "<title>MoneyPrinter - Why this contract?</title><style>" + CSS + "</style><main>",
              "<button onclick=\"document.body.classList.toggle('light')\">Light / dark</button>",
              "<h1>Why this contract?</h1><p class='note'>Research hypotheses, not live orders or validated recommendations. "
              "Explanations describe frozen inputs, never later outcomes.</p>",
              f"<p>Decision: <b>{esc(record.get('decision_date'))}</b> | Source: {esc(source)}<br>"
              f"Record checksum: <code>{esc(record.get('record_sha256', 'legacy picks-only hash'))}</code></p>"]
    name = input_name(record)
    if name:
        chunks.append(f"<p><a href='{name}'>Open exact decision-time input slice</a></p>")
    for index, original in enumerate(record.get("picks", [])):
        p = original if original.get("explanation") else attach_explanation(original, record.get("source_files"))
        e = p["explanation"]
        if not verify_explanation(e):
            raise ValueError(f"Explanation integrity failed at pick {index}")
        ident = e["details_fingerprint_sha256"]
        chunks.append(f"<article id='pick-{index}'><h2>{index}: {esc(p.get('ticker'))} - "
                      f"{esc(p.get('variant'))} - {esc(p.get('action'))}</h2><p>{esc(e['short_justification'])}</p>"
                      f"<p class='note'>Gate: {esc(p.get('gate_decision', 'ABSTAIN'))}. "
                      f"Reason: {esc(p.get('reason') or ', '.join(p.get('gate_failed', [])))}</p>"
                      "<details><summary>Indicators, weights and exact contributions</summary><div class='scroll'>"
                      "<table><thead><tr><th>Indicator</th><th>Scaled value</th><th>Weight</th><th>Contribution</th></tr></thead><tbody>")
        for d in e["details"].get("indicator_contributions", []):
            chunks.append("<tr>" + "".join(f"<td>{esc(d.get(k))}</td>" for k in
                          ("indicator", "scaled_value", "weight", "weighted_contribution")) + "</tr>")
        chunks.append("</tbody></table></div><p>Contributions sum to " + esc(e["details"].get("contribution_sum")) +
                      ". They explain this rule, not causation or probability of profit.</p></details>")
        for title, value in (("Full contract, liquidity and selection alternatives", {
                "contract": p.get("contract"), "selection_metrics": p.get("selection_metrics"),
                "selection_audit": p.get("selection_audit"), "rationale": p.get("rationale")}),
                ("Decision inputs, timestamps, source identities and checksum", e)):
            chunks.append(f"<details><summary>{title}</summary><pre>{esc(json.dumps(value, indent=2, default=str, allow_nan=False))}</pre></details>")
        if not original.get("explanation"):
            chunks.append("<p class='note'>Legacy explanation reconstructed from frozen fields; it was not recorded at generation.</p>")
        chunks.append(f"<p class='note'>Explanation ID: <code>{ident}</code> | <a href='#pick-{index}'>Link to this pick</a></p></article>")
    return "\n".join(chunks) + "</main></html>"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    paths = get_paths()
    candidates = sorted(paths.picks.glob("picks_*.json"))
    path = args.file or (candidates[-1] if candidates else None)
    if path is None:
        print("No frozen picks yet. Generate picks or select a historical replay pick file.")
        return 1
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        page = render(record, path.name)
        target = args.out or paths.root / "reviews" / (path.stem + ".html")
        target.parent.mkdir(parents=True, exist_ok=True)
        name = input_name(record)
        if name:
            source = path.parent / name
            value = json.loads(source.read_text("utf-8"))
            if digest(value) != record["source_files"]["visible_input_sha256"]:
                raise ValueError("Decision input checksum failed")
            destination = target.parent / name
            if destination.resolve() != source.resolve():
                encoded = source.read_bytes()
                if destination.exists() and destination.read_bytes() != encoded:
                    raise ValueError("Refusing to replace a different decision input file")
                if not destination.exists():
                    with destination.open("xb") as output:
                        output.write(encoded)
        target.write_text(page, encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"Review written: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
