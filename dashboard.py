#!/usr/bin/env python3
"""
Build a single self-contained HTML dashboard: picks, rationale, backtest.

    python dashboard.py                  # newest picks + newest backtest
    python dashboard.py --open           # ...and open it in a browser
    python dashboard.py --picks picks/picks_2026-09-05_120000.json

WHY A FILE AND NOT A WINDOW
It has to work offline on a machine that has never seen this repository, which
is what "take the app and data into an offline environment" needs. So the output
is ONE .html file with every style, every number and every chart inlined - no
CDN, no fonts to fetch, no JavaScript library, no server. Open it from a USB
stick on a laptop with the wifi off and it renders identically.

That also settles what Excel is for. The workbook is the audit trail - every bar,
every label, every Greek, in a form you can sort and pivot and check the arithmetic
of. This page is the reading surface: what the picks are, why, and whether the
signal behind them has ever been shown to work.

WHAT IT WILL NOT DO
It will not show an equity curve for the options picks. No historical option
chains exist in this data (Yahoo serves current chains only), so any such curve
would be drawn from numbers nobody observed. The backtest section measures the
SIGNAL layer on the underlying and says so on its face.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PICKS_DIR = HERE / "picks"
DEFAULT_BACKTEST_DIR = HERE / "backtests"
DEFAULT_OUT = HERE / "dashboard.html"

# Dark surface palette, from the validated reference instance. Checked with the
# palette validator at three categorical slots on the #1a1a19 surface: lightness
# band, chroma floor, CVD separation, normal-vision floor and contrast all pass.
CSS = """
:root {
  --surface-0:#111110; --surface-1:#1a1a19; --surface-2:#232320; --line:#33332f;
  --text-1:#ffffff; --text-2:#c3c2b7; --text-3:#8a897f;
  --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
  --pos:#3987e5; --neg:#d03b3b; --mid:#383835;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--surface-0); color:var(--text-1);
  font:14px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
.wrap { max-width:1180px; margin:0 auto; padding:28px 22px 72px; }
h1 { font-size:21px; margin:0 0 2px; letter-spacing:-.01em; }
h2 { font-size:15px; margin:0; letter-spacing:.06em; text-transform:uppercase; color:var(--text-2); }
h3 { font-size:14px; margin:0 0 2px; }
.sub { color:var(--text-3); font-size:12.5px; margin:0; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
section { margin-top:26px; }
.head { display:flex; align-items:baseline; gap:12px; border-left:3px solid var(--series-1);
  padding-left:10px; margin-bottom:12px; }
.card { background:var(--surface-1); border:1px solid var(--line); border-radius:10px; padding:16px 18px; }
.grid { display:grid; gap:12px; }
.note { background:var(--surface-1); border:1px solid var(--line); border-left:3px solid var(--warning);
  border-radius:8px; padding:13px 16px; color:var(--text-2); font-size:13px; }
.note b { color:var(--text-1); }
.stat { background:var(--surface-1); border:1px solid var(--line); border-radius:10px; padding:13px 15px; }
.stat .k { font-size:10.5px; letter-spacing:.09em; text-transform:uppercase; color:var(--text-3); }
.stat .v { font-size:22px; font-weight:600; margin-top:3px; letter-spacing:-.02em; }
.stat .n { font-size:11.5px; color:var(--text-3); margin-top:1px; }
.chip { display:inline-flex; align-items:center; gap:5px; font-size:11px; font-weight:600;
  letter-spacing:.05em; padding:3px 9px; border-radius:999px; border:1px solid; }
.chip.good{ color:var(--good); border-color:var(--good); }
.chip.warn{ color:var(--warning); border-color:var(--warning); }
.chip.bad { color:var(--critical); border-color:var(--critical); }
.chip.mute{ color:var(--text-3); border-color:var(--line); }
table { border-collapse:collapse; width:100%; font-size:12.5px; }
th { text-align:right; font-weight:600; color:var(--text-3); font-size:10.5px; letter-spacing:.07em;
  text-transform:uppercase; padding:0 10px 7px; border-bottom:1px solid var(--line); }
th:first-child, td:first-child { text-align:left; }
td { padding:7px 10px; border-bottom:1px solid var(--surface-2); text-align:right;
  font-variant-numeric:tabular-nums; }
tr:last-child td { border-bottom:0; }
.scroll { overflow-x:auto; }
.why { color:var(--text-2); font-size:13px; margin:10px 0 0; padding-top:10px;
  border-top:1px solid var(--surface-2); }
.kv { display:flex; flex-wrap:wrap; gap:5px 20px; font-size:12.5px; color:var(--text-2); margin-top:8px; }
.kv b { color:var(--text-1); font-weight:600; font-variant-numeric:tabular-nums; }
.pickhead { display:flex; flex-wrap:wrap; align-items:center; gap:10px; }
.tk { font-size:17px; font-weight:700; letter-spacing:-.01em; }
.var { font-size:11px; letter-spacing:.07em; text-transform:uppercase; color:var(--text-3); }
svg { display:block; max-width:100%; }
.legend { display:flex; flex-wrap:wrap; gap:14px; font-size:11.5px; color:var(--text-2); margin-top:10px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px;
  vertical-align:-1px; }
footer { margin-top:36px; padding-top:16px; border-top:1px solid var(--line);
  color:var(--text-3); font-size:12px; }
.empty { color:var(--text-3); font-size:13px; }
"""


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def num(v, fmt: str, dash: str = "—") -> str:
    return format(v, fmt) if isinstance(v, (int, float)) and v == v else dash


def newest(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern)) if folder.is_dir() else []
    return files[-1] if files else None


# ---------------------------------------------------------------------------
# Charts. Inline SVG, no library - a dependency that must be fetched is a
# dependency that fails on the offline machine this page exists for.
# ---------------------------------------------------------------------------

def accuracy_chart(variants: list[dict]) -> str:
    """Accuracy against its own noise floor, one row per variant.

    The bar is the measured accuracy. The band behind it is the permuted noise
    floor at +/- one standard deviation, and the tick is the majority-class rate.
    Drawing all three together is the point: an accuracy bar alone is unreadable,
    and reading one without its floor is how a coin flip becomes a strategy.
    """
    if not variants:
        return '<p class="empty">No backtest yet.</p>'
    lo, hi = 0.30, 0.70
    W, ROW, PAD_L, PAD_T = 720, 34, 150, 24
    H = PAD_T + ROW * len(variants) + 26

    def x(v: float) -> float:
        return PAD_L + (max(lo, min(hi, v)) - lo) / (hi - lo) * (W - PAD_L - 60)

    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Accuracy versus noise floor">']
    for g in (0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65):
        out.append(f'<line x1="{x(g):.1f}" y1="{PAD_T-6}" x2="{x(g):.1f}" y2="{H-24}" '
                   f'stroke="var(--line)" stroke-width="1"/>')
        out.append(f'<text x="{x(g):.1f}" y="{H-8}" fill="var(--text-3)" font-size="10" '
                   f'text-anchor="middle">{g:.2f}</text>')
    for i, v in enumerate(variants):
        y = PAD_T + i * ROW
        acc, floor, sd = v["accuracy"], v["permutation_mean"], v["permutation_std"]
        maj = v["majority_class_rate"]
        beat = isinstance(acc, float) and isinstance(maj, float) and acc > maj
        colour = "var(--good)" if beat and v.get("z", 0) > 2 else "var(--series-1)"
        if isinstance(floor, float) and isinstance(sd, float):
            bx, bw = x(floor - sd), max(2.0, x(floor + sd) - x(floor - sd))
            out.append(f'<rect x="{bx:.1f}" y="{y+3}" width="{bw:.1f}" height="18" '
                       f'fill="var(--mid)" rx="3"><title>noise floor '
                       f'{floor:.4f} ± {sd:.4f}</title></rect>')
        if isinstance(acc, float):
            out.append(f'<rect x="{PAD_L}" y="{y+8}" width="{max(2.0, x(acc)-PAD_L):.1f}" '
                       f'height="8" fill="{colour}" rx="4"><title>accuracy '
                       f'{acc:.4f}</title></rect>')
        if isinstance(maj, float):
            out.append(f'<line x1="{x(maj):.1f}" y1="{y+1}" x2="{x(maj):.1f}" y2="{y+23}" '
                       f'stroke="var(--warning)" stroke-width="2"><title>majority class '
                       f'{maj:.4f}</title></line>')
        out.append(f'<text x="{PAD_L-12}" y="{y+17}" fill="var(--text-2)" font-size="12" '
                   f'text-anchor="end">{esc(v["strategy"])}</text>')
        out.append(f'<text x="{W-52}" y="{y+17}" fill="var(--text-2)" font-size="11.5" '
                   f'font-family="ui-monospace,monospace">{num(acc, ".3f")}</text>')
    out.append("</svg>")
    out.append('<div class="legend">'
               '<span><i style="background:var(--series-1)"></i>measured accuracy</span>'
               '<span><i style="background:var(--good)"></i>beats the majority class AND clears '
               'the floor by 2 sd &mdash; see the verdict column, never the colour alone</span>'
               '<span><i style="background:var(--mid)"></i>noise floor, permuted &plusmn;1 sd</span>'
               '<span><i style="background:var(--warning)"></i>majority-class rate</span></div>')
    return "".join(out)


def ic_chart(rows: list[dict]) -> str:
    """Rank IC per component: diverging around zero, because sign is the point.

    A component whose IC is negative is not weak, it is backwards - so the axis
    has a real midpoint and the two arms take the diverging pair. The thin line
    behind each bar is the fold-to-fold spread at +/- one standard deviation; when
    it straddles zero, the mean is decoration.
    """
    if not rows:
        return '<p class="empty">No backtest yet.</p>'
    span = max([0.05] + [abs(r["mean"]) + (r["stdev"] or 0)
                         for r in rows if isinstance(r.get("mean"), float)])
    span = min(span * 1.15, 1.0)
    W, ROW, PAD_L, PAD_T = 720, 34, 150, 24
    H = PAD_T + ROW * len(rows) + 26
    mid = PAD_L + (W - PAD_L - 60) / 2

    def x(v: float) -> float:
        return mid + max(-span, min(span, v)) / span * ((W - PAD_L - 60) / 2)

    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Rank IC per component">']
    for g in (-span, -span / 2, 0.0, span / 2, span):
        out.append(f'<line x1="{x(g):.1f}" y1="{PAD_T-6}" x2="{x(g):.1f}" y2="{H-24}" '
                   f'stroke="{"var(--text-3)" if g == 0 else "var(--line)"}" stroke-width="1"/>')
        out.append(f'<text x="{x(g):.1f}" y="{H-8}" fill="var(--text-3)" font-size="10" '
                   f'text-anchor="middle">{g:+.2f}</text>')
    for i, r in enumerate(rows):
        y = PAD_T + i * ROW
        m, sd = r.get("mean"), r.get("stdev")
        if isinstance(m, float):
            if isinstance(sd, float):
                out.append(f'<line x1="{x(m-sd):.1f}" y1="{y+12}" x2="{x(m+sd):.1f}" y2="{y+12}" '
                           f'stroke="var(--text-3)" stroke-width="1.5" stroke-linecap="round">'
                           f'<title>fold spread {m-sd:+.3f} to {m+sd:+.3f}</title></line>')
            x0, x1 = (mid, x(m)) if m >= 0 else (x(m), mid)
            out.append(f'<rect x="{min(x0,x1):.1f}" y="{y+8}" width="{max(2.0, abs(x1-x0)):.1f}" '
                       f'height="8" rx="4" fill="{"var(--pos)" if m >= 0 else "var(--neg)"}">'
                       f'<title>mean IC {m:+.4f} over {r["folds"]} folds</title></rect>')
        out.append(f'<text x="{PAD_L-12}" y="{y+17}" fill="var(--text-2)" font-size="12" '
                   f'text-anchor="end">{esc(r["component"])}</text>')
        out.append(f'<text x="{W-52}" y="{y+17}" fill="var(--text-2)" font-size="11.5" '
                   f'font-family="ui-monospace,monospace">{num(m, "+.3f")}</text>')
    out.append("</svg>")
    out.append('<div class="legend">'
               '<span><i style="background:var(--pos)"></i>positive mean IC</span>'
               '<span><i style="background:var(--neg)"></i>negative &mdash; the component is backwards</span>'
               '<span><i style="background:var(--text-3)"></i>fold spread &plusmn;1 sd</span></div>')
    return "".join(out)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def verdict_chip(verdict: str) -> str:
    v = (verdict or "").upper()
    if "SIGNAL_CANDIDATE" in v:
        cls, icon = "good", "&#9679;"
    elif "INCONCLUSIVE" in v:
        cls, icon = "warn", "&#9679;"
    else:
        cls, icon = "mute", "&#9679;"
    return f'<span class="chip {cls}">{icon} {esc(verdict)}</span>'


def gate_chip(decision: str) -> str:
    d = (decision or "").upper()
    cls = {"PAPER_TRADE_CANDIDATE": "good", "WATCH": "warn"}.get(d, "mute")
    return f'<span class="chip {cls}">GATE {esc(decision)}</span>'


def picks_section(doc: dict | None, path: Path | None) -> str:
    if not doc:
        return ('<div class="card"><p class="empty">No pick file yet. Press '
                '<b>3 &middot; Generate paper picks</b> in the app, or run '
                '<span class="mono">python generate_picks.py</span>.</p></div>')
    picks = doc.get("picks", [])
    proposed = [p for p in picks if p.get("action") != "ABSTAIN"]
    abstained = [p for p in picks if p.get("action") == "ABSTAIN"]
    policy = doc.get("exit_policy", {})

    out = [f'<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">']
    for k, v, n in (("Decision date", doc.get("decision_date"), "the 15:45 ET clock"),
                    ("Proposed", len(proposed), f"{len(abstained)} abstentions"),
                    ("Universe", ", ".join(doc.get("universe", [])) or "—", "instruments considered"),
                    ("Frozen SHA-256", (doc.get("picks_sha256") or "")[:12] or "—",
                     "cannot be edited after the fact")):
        out.append(f'<div class="stat"><div class="k">{esc(k)}</div>'
                   f'<div class="v mono" style="font-size:{"15px" if k in ("Universe","Frozen SHA-256") else "22px"}">'
                   f'{esc(v)}</div><div class="n">{esc(n)}</div></div>')
    out.append("</div>")

    rules = doc.get("exit_policy_plain_english") or []
    if policy or rules:
        if rules:
            out.append('<div class="note" style="margin-top:12px"><b>Exit rules, fixed now, '
                       'before any outcome is known.</b><ul style="margin:7px 0 0;padding-left:18px">'
                       + "".join(f"<li>{esc(r)}</li>" for r in rules) + "</ul></div>")

    if not proposed:
        out.append('<div class="card" style="margin-top:12px"><p class="empty">'
                   'Every variant abstained. That is the default and it is a result, not a failure.'
                   '</p></div>')
    for p in proposed:
        c = p.get("contract", {})
        out.append('<div class="card" style="margin-top:12px">')
        out.append(f'<div class="pickhead"><span class="tk">{esc(p.get("ticker"))}</span>'
                   f'<span class="chip mute">{esc(p.get("action"))}</span>'
                   f'<span class="var">{esc(p.get("variant"))}</span>'
                   f'<span style="flex:1"></span>{gate_chip(p.get("gate_decision", ""))}</div>')
        out.append('<div class="kv">')
        for k, v in (("Contract", f'{c.get("expiration","?")}  {c.get("strike","?")} {c.get("type","?")}'),
                     ("DTE", c.get("dte")), ("Delta", num(c.get("delta"), "+.2f")),
                     ("IV", num(c.get("iv_solved"), ".1%")),
                     ("Bid/Ask", f'{num(c.get("bid"), ".2f")} / {num(c.get("ask"), ".2f")}'),
                     ("Spread", num(c.get("relative_spread"), ".1%")),
                     ("Entry est", num(p.get("entry_fill_estimate"), ".2f")),
                     ("Breakeven move", num(p.get("breakeven_move_pct"), ".2%")),
                     ("Score", num(p.get("composite_score"), "+.2f"))):
            out.append(f"<span>{esc(k)} <b>{esc(v)}</b></span>")
        out.append("</div>")
        if p.get("gate_failed"):
            out.append(f'<div class="kv"><span>Gate failures <b>'
                       f'{esc(", ".join(p["gate_failed"]))}</b></span></div>')
        out.append(f'<p class="why"><b>Why:</b> {esc(p.get("rationale"))}</p>')
        out.append("</div>")

    if abstained:
        out.append('<div class="card" style="margin-top:12px"><h3>Abstentions '
                   f'({len(abstained)})</h3><p class="sub">Recorded, not discarded. A variant '
                   'that abstains on every run is telling you something about the variant.</p>'
                   '<div class="scroll"><table><thead><tr><th>Variant</th><th>Ticker</th>'
                   '<th>Reason</th></tr></thead><tbody>')
        for p in abstained:
            out.append(f'<tr><td>{esc(p.get("variant"))}</td><td>{esc(p.get("ticker"))}</td>'
                       f'<td style="text-align:left;color:var(--text-2)">{esc(p.get("reason"))}</td></tr>')
        out.append("</tbody></table></div></div>")

    if path:
        out.append(f'<p class="sub" style="margin-top:10px">Source: '
                   f'<span class="mono">{esc(path.name)}</span></p>')
    return "".join(out)


def backtest_section(bt: dict | None, path: Path | None) -> str:
    if not bt:
        return ('<div class="card"><p class="empty">No backtest yet. Press '
                '<b>5 &middot; Backtest the signal</b> in the app, or run '
                '<span class="mono">python backtest.py</span>.</p></div>')
    # Each entry is a VariantResult: the numbers live on its nested report.
    variants = []
    for v in (bt.get("variants") or []):
        r = v.get("report") or {}
        variants.append({
            "strategy": r.get("strategy_name") or v.get("variant"),
            "description": v.get("description", ""),
            "accuracy": r.get("accuracy"),
            "majority_class_rate": r.get("majority_class_rate"),
            "permutation_mean": r.get("permutation_mean"),
            "permutation_std": r.get("permutation_std"),
            "z": r.get("z_vs_noise"),
            "p": r.get("permutation_p_value"),
            "verdict": r.get("verdict"),
            "folds": len(r.get("folds") or []),
            "n_test": v.get("n_test"),
        })
    ic = [{"component": r.get("component"), "mean": r.get("mean"), "stdev": r.get("stdev"),
           "hit_rate": r.get("hit_rate"), "t": r.get("t_stat"),
           "folds": len(r.get("per_fold") or [])} for r in (bt.get("rank_ic") or [])]

    s = bt.get("settings", {})
    out = ['<div class="note"><b>This is not an options backtest, and cannot be one.</b> '
           'Yahoo serves current option chains only, so no historical chain exists to price a '
           'contract against &mdash; any options equity curve drawn from this data would be '
           'fabricated. What is measured here is the <b>signal on the underlying</b>: does a '
           'weighted blend of the components predict the sign of 5-trading-day forward excess '
           'return versus SPY, out of sample? If it does not, no options overlay rescues it.</div>']

    out.append('<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));'
               'margin-top:12px">')
    for k, v, n in (("Observations", bt.get("observations"), "complete features + resolved label"),
                    ("Folds", len(bt.get("splits") or []),
                     f'{s.get("train_sessions","?")} train / {s.get("label_horizon_sessions","?")} purge '
                     f'/ {s.get("test_sessions","?")} test sessions'),
                    ("Sessions", bt.get("sessions"), "trading days in the store"),
                    ("Permutations", s.get("n_permutations"), "block-permuted, model refit"),
                    ("Window", f'{bt.get("first_decision","?")} → {bt.get("last_decision","?")}',
                     "decision dates covered")):
        size = "14px" if k == "Window" else "22px"
        out.append(f'<div class="stat"><div class="k">{esc(k)}</div>'
                   f'<div class="v mono" style="font-size:{size}">{esc(v)}</div>'
                   f'<div class="n">{esc(n)}</div></div>')
    out.append("</div>")

    out.append('<div class="card" style="margin-top:14px"><h3>Accuracy against its own noise floor</h3>'
               '<p class="sub">A bar left of the amber tick loses to always guessing the common '
               'answer. A bar inside the grey band is indistinguishable from the same procedure run '
               'on shuffled labels.</p>' + accuracy_chart(variants) + "</div>")

    out.append('<div class="card" style="margin-top:12px"><div class="scroll"><table><thead><tr>'
               '<th>Variant</th><th>Accuracy</th><th>Majority</th><th>Noise floor</th>'
               '<th>z</th><th>p</th><th>Verdict</th></tr></thead><tbody>')
    for v in variants:
        out.append(f'<tr><td>{esc(v["strategy"])}</td><td>{num(v["accuracy"], ".4f")}</td>'
                   f'<td>{num(v["majority_class_rate"], ".4f")}</td>'
                   f'<td>{num(v["permutation_mean"], ".4f")} ± {num(v["permutation_std"], ".4f")}</td>'
                   f'<td>{num(v["z"], "+.2f")}</td><td>{num(v["p"], ".4f")}</td>'
                   f'<td>{verdict_chip(v["verdict"])}</td></tr>')
    out.append("</tbody></table></div></div>")

    out.append('<div class="card" style="margin-top:12px"><h3>Rank IC per component</h3>'
               '<p class="sub">Does the component&rsquo;s ranking of instruments match the ranking '
               'of their forward excess returns? Measured out of sample, once per test window. This '
               'is what justifies or retires a component on its own rather than inside a blend.</p>'
               + ic_chart(ic))
    out.append('<div class="scroll" style="margin-top:12px"><table><thead><tr><th>Component</th>'
               '<th>Mean IC</th><th>Std dev</th><th>Sign held</th><th>t</th><th>Folds</th>'
               '</tr></thead><tbody>')
    for r in ic:
        out.append(f'<tr><td>{esc(r["component"])}</td><td>{num(r["mean"], "+.4f")}</td>'
                   f'<td>{num(r["stdev"], ".4f")}</td><td>{num(r["hit_rate"], ".0%")}</td>'
                   f'<td>{num(r["t"], "+.2f")}</td><td>{r["folds"]}</td></tr>')
    out.append('</tbody></table></div><p class="sub" style="margin-top:10px">A mean IC whose sign '
               'does not hold across folds is not a weak edge. It is no edge, measured several '
               'times. The t column assumes folds are independent, which they are not &mdash; '
               'treat it as a magnitude cue, not a p-value.</p></div>')

    if path:
        out.append(f'<p class="sub" style="margin-top:10px">Source: '
                   f'<span class="mono">{esc(path.name)}</span></p>')
    return "".join(out)


MAP_STAGES = [
    ("I–III", "Foundations, market architecture, market theory", "done",
     "Point-in-time store, four-timestamp evidence contract, US-Eastern clock."),
    ("IV", "Edge mechanisms", "open",
     "No mechanism is claimed. The components are technical constructions with no "
     "stated reason a market would pay for them &mdash; the honest gap."),
    ("V", "Observable world", "done",
     "Daily bars and current option chains, each carrying when it became knowable."),
    ("VI", "Feature engineering", "done",
     "Five scaled components: momentum 20d/60d, trend, low volatility, reversion."),
    ("VII", "Hypothesis", "done",
     "Sign of 5-trading-day forward excess return versus SPY. Label contract v1.0."),
    ("VIII", "Validation", "running",
     "Walk-forward with a session-purged gap, a refit permutation null, and "
     "per-component rank IC. This is where the project currently sits."),
    ("IX–X", "Forecast / signal, decision policy", "done",
     "Composite score, conviction floor, and a deterministic risk gate whose "
     "default is PASS &mdash; do nothing."),
    ("XI", "Strategy", "partial",
     "Five variants logged together, including a deliberately contradictory one."),
    ("XII–XV", "Factors, multi-factor, ensembles, portfolio construction", "open",
     "Not started, and correctly so: they compose edges, and no edge is established."),
    ("XVI", "Implementation", "n/a",
     "No live order path exists anywhere in this repository, by design."),
    ("XVII", "Live research", "running",
     "The forward paper record: frozen hashed picks, scored later by a separate program."),
]


def map_section() -> str:
    tone = {"done": ("good", "built"), "running": ("warn", "in progress"),
            "partial": ("warn", "partial"), "open": ("mute", "not started"),
            "n/a": ("mute", "out of scope")}
    out = ['<p class="sub">Where this repository sits on the quant spine &mdash; theory to '
           'mechanism to observable to feature to hypothesis to test to signal to strategy. '
           'The value of the map is that it makes the missing stage obvious, and here that is '
           '<b style="color:var(--text-1)">IV, edge mechanisms</b>: every component below it is '
           'built and tested, and not one of them has a stated reason a market would pay for it.</p>'
           '<div class="scroll" style="margin-top:12px"><table><thead><tr><th>Stage</th>'
           '<th style="text-align:left">Name</th><th>State</th>'
           '<th style="text-align:left">Where it stands</th></tr></thead><tbody>']
    for stage, name, state, detail in MAP_STAGES:
        cls, label = tone[state]
        out.append(f'<tr><td class="mono">{esc(stage)}</td>'
                   f'<td style="text-align:left">{esc(name)}</td>'
                   f'<td><span class="chip {cls}">{esc(label)}</span></td>'
                   f'<td style="text-align:left;color:var(--text-2)">{detail}</td></tr>')
    out.append("</tbody></table></div>")
    return "".join(out)


def render(picks: dict | None, picks_path: Path | None,
           bt: dict | None, bt_path: Path | None) -> str:
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Money Printer — picks and evidence</title>
<style>{CSS}</style></head><body><div class="wrap">

<header>
  <h1>Money Printer &mdash; picks and evidence</h1>
  <p class="sub">Built {esc(built)} &middot; self-contained, works offline &middot;
     <b style="color:var(--warning)">paper/simulation only &mdash; no live order path exists
     in this repository</b></p>
</header>

<section><div class="head"><h2>Picks</h2><p class="sub">frozen and hashed at generation</p></div>
{picks_section(picks, picks_path)}</section>

<section><div class="head"><h2>Does the signal work?</h2>
  <p class="sub">walk-forward, out of sample, against a noise floor</p></div>
{backtest_section(bt, bt_path)}</section>

<section><div class="head"><h2>Where this sits on the quant map</h2></div>
<div class="card">{map_section()}</div></section>

<footer>
  The Excel workbook is the audit trail &mdash; every bar, label and Greek, in a form you can
  sort and check the arithmetic of. This page is the reading surface. Neither is advice.
  <br>Nothing here has a measured edge; the risk gate&rsquo;s default verdict is PASS, meaning
  do nothing, and every pick records that verdict verbatim.
</footer>

</div></body></html>"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--picks", default=None, help="a pick file; default is the newest")
    ap.add_argument("--backtest", default=None, help="a backtest file; default is the newest")
    ap.add_argument("--picks-dir", default=str(DEFAULT_PICKS_DIR))
    ap.add_argument("--backtest-dir", default=str(DEFAULT_BACKTEST_DIR))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--open", action="store_true", help="open it in a browser afterwards")
    a = ap.parse_args(argv)

    pp = Path(a.picks) if a.picks else newest(Path(a.picks_dir), "picks_*.json")
    bp = Path(a.backtest) if a.backtest else newest(Path(a.backtest_dir), "backtest_*.json")

    picks = json.loads(pp.read_text(encoding="utf-8")) if pp and pp.is_file() else None
    bt = json.loads(bp.read_text(encoding="utf-8")) if bp and bp.is_file() else None

    out = Path(a.out).expanduser().resolve()
    out.write_text(render(picks, pp if picks else None, bt, bp if bt else None), encoding="utf-8")

    print(f"Picks    : {pp if picks else 'none found — run generate_picks.py'}")
    print(f"Backtest : {bp if bt else 'none found — run backtest.py'}")
    print(f"Written  : {out}")
    print("\nOne file, no external assets. Copy it anywhere and it still renders.")
    if a.open:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
