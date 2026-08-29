#!/usr/bin/env python3
"""
Turn the point-in-time data store into an Excel workbook you can actually work in.

    python excel_report.py                       # every ticker in the store
    python excel_report.py --tickers SPY,MSFT    # just these
    python excel_report.py --out book.xlsx       # explicit path

Reads the immutable vintage files written by claude/app/mp_v01/fetch_data.py and
writes one .xlsx containing:

    README        what this is, when it was built, which files it came from
    Summary       one row per ticker: coverage, gaps, label base rate
    Bars_<TICKER> one sheet per ticker - OHLCV, dividends, daily total return,
                  the two point-in-time timestamps, plus live Excel formulas for
                  SMA20 / SMA50 / 20-day annualised vol so you can retune the
                  windows in the sheet without re-running Python
    Labels        the label contract v1.0 target, built by importing the real
                  labels/contract.py - not a re-implementation that can drift

WHAT THIS DELIBERATELY DOES NOT DO
Nothing here interpolates, forward-fills, or estimates. A missing bar stays
missing, breaks the return chain, and turns the affected labels UNRESOLVED
rather than being bridged. Blank cells in the Excel output are real gaps.

The labels are FORWARD-LOOKING by construction (that is what a training target
is). They are correct to use for fitting and scoring. They are not something a
decision at that row's date could have seen. Everything to the left of the
Labels sheet is point-in-time; the Labels sheet is the answer key.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
MP_V01_DIR = HERE / "claude" / "app" / "mp_v01"
DEFAULT_DATA_DIR = MP_V01_DIR / "data_store"
DEFAULT_OUT_DIR = HERE / "excel_out"

# The label contract is imported, never re-derived here. If the definition of
# the target changes in the codebase, this workbook changes with it.
sys.path.insert(0, str(MP_V01_DIR / "src"))
from labels.contract import (  # noqa: E402
    BENCHMARK,
    HORIZON_TRADING_DAYS,
    LABEL_CONTRACT_VERSION,
    build_label,
)


# ---------------------------------------------------------------------------
# Loading the store
# ---------------------------------------------------------------------------

def find_bar_files(data_dir: Path) -> dict[str, Path]:
    """Newest vintage per ticker under <data_dir>/bars.

    fetch_data.py never overwrites: every run drops a new
    ``TICKER_start_end__vYYYYmmddTHHMMSSZ.json``. Older vintages are kept on
    purpose, so a report has to pick one. It picks the newest, and the README
    sheet records exactly which file that was.
    """
    bars_dir = data_dir / "bars"
    if not bars_dir.is_dir():
        return {}

    newest: dict[str, tuple[str, Path]] = {}
    for path in sorted(bars_dir.glob("*.json")):
        head, sep, vintage = path.stem.partition("__v")
        if not sep:
            continue                      # not a vintage file; ignore quietly
        ticker = head.split("_")[0].upper()
        # Vintage ids are UTC ISO-basic, so lexical order is chronological.
        if ticker not in newest or vintage > newest[ticker][0]:
            newest[ticker] = (vintage, path)
    return {t: p for t, (_, p) in sorted(newest.items())}


def load_bar_doc(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    doc.setdefault("rows", [])
    doc["_source_file"] = path.name
    return doc


def dated_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows carrying a usable date, in date order.

    Rows the adapter marked UNKNOWN keep their place in the Bars sheet (a gap
    you can see is worth more than a gap you can't), but a row with no date at
    all cannot be positioned on a calendar and is dropped here.
    """
    rows = [r for r in doc.get("rows", []) if r.get("date")]
    return sorted(rows, key=lambda r: r["date"])


# ---------------------------------------------------------------------------
# Labels - built with the real contract, not a copy of it
# ---------------------------------------------------------------------------

def returns_by_date(rows: Iterable[dict[str, Any]]) -> dict[str, float | None]:
    return {r["date"]: r.get("daily_total_return") for r in rows if r.get("date")}


def build_labels_for(
    ticker: str,
    rows: list[dict[str, Any]],
    benchmark_returns: dict[str, float | None],
) -> list[dict[str, Any]]:
    """One label row per bar date, including the unresolved tail.

    The last few dates in any file resolve to INSUFFICIENT_FORWARD_BARS because
    their 5-day outcome has not happened yet. Those rows are kept rather than
    hidden: "we don't know yet" is a different statement from "no signal", and
    silently truncating them is how a sheet starts lying about its coverage.
    """
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        decision_date = row["date"]
        forward = rows[i + 1 : i + 1 + HORIZON_TRADING_DAYS]
        inst_returns = [r.get("daily_total_return") for r in forward]
        # Benchmark returns are aligned by DATE, never by row index: two tickers
        # can have different halted/missing sessions, and index alignment would
        # quietly score a stock against the wrong day of SPY.
        bench_returns = [benchmark_returns.get(r["date"]) for r in forward]

        label = build_label(
            ticker,
            decision_date,
            inst_returns,
            bench_returns,
        )
        out.append(
            {
                "ticker": ticker,
                "decision_date": decision_date,
                "decision_time_utc": label.decision_time_utc.isoformat(),
                "horizon_trading_days": label.horizon_trading_days,
                "y": label.y,
                "excess_log_return": label.excess_log_return,
                "status": label.status.value,
                "usable": label.is_usable(),
                "benchmark": "n/a (is benchmark)" if ticker == BENCHMARK else BENCHMARK,
                "contract_version": label.contract_version,
            }
        )
    return out


def summarize(ticker: str, doc: dict[str, Any], rows: list[dict[str, Any]],
               labels: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [l for l in labels if l["usable"]]
    ones = sum(1 for l in usable if l["y"] == 1)
    closes = [r.get("close") for r in rows if r.get("close") is not None]
    return {
        "ticker": ticker,
        "source_file": doc.get("_source_file", "UNKNOWN"),
        "vintage_id": doc.get("vintage_id", "UNKNOWN"),
        "ingested_time": doc.get("ingested_time", "UNKNOWN"),
        "source": doc.get("source", "UNKNOWN"),
        "bars": len(rows),
        "first_date": rows[0]["date"] if rows else "",
        "last_date": rows[-1]["date"] if rows else "",
        "last_close": closes[-1] if closes else None,
        "usable_returns": sum(1 for r in rows if r.get("daily_total_return") is not None),
        "gap_rows": sum(1 for r in rows if r.get("daily_total_return") is None),
        "labels_total": len(labels),
        "labels_usable": len(usable),
        "labels_unresolved": len(labels) - len(usable),
        "base_rate_y1": (ones / len(usable)) if usable else None,
    }


def collect(data_dir: Path, only: list[str] | None = None) -> dict[str, Any]:
    """Everything the workbook needs, with no Excel dependency in sight."""
    files = find_bar_files(data_dir)
    if only:
        wanted = {t.strip().upper() for t in only if t.strip()}
        files = {t: p for t, p in files.items() if t in wanted}

    docs = {t: load_bar_doc(p) for t, p in files.items()}
    rows = {t: dated_rows(d) for t, d in docs.items()}

    # Excess return is defined against SPY. Without SPY in the store the target
    # is undefined for everything else, and inventing a substitute benchmark
    # would silently change what the model is being asked to predict.
    benchmark_present = BENCHMARK in rows and any(
        r.get("daily_total_return") is not None for r in rows[BENCHMARK]
    )
    bench = returns_by_date(rows[BENCHMARK]) if benchmark_present else {}

    labels: dict[str, list[dict[str, Any]]] = {}
    for ticker, rs in rows.items():
        if ticker == BENCHMARK or benchmark_present:
            labels[ticker] = build_labels_for(ticker, rs, bench)
        else:
            labels[ticker] = []

    summaries = [summarize(t, docs[t], rows[t], labels[t]) for t in sorted(rows)]

    return {
        "generated_utc": datetime.now(timezone.utc),
        "data_dir": str(data_dir),
        "files": {t: str(p) for t, p in files.items()},
        "docs": docs,
        "rows": rows,
        "labels": labels,
        "summaries": summaries,
        "benchmark_present": benchmark_present,
    }


# ---------------------------------------------------------------------------
# Excel writing (the only part that needs openpyxl)
# ---------------------------------------------------------------------------

HEADER_FILL = "1F3B4D"
BAR_COLUMNS = [
    ("date", 12, "yyyy-mm-dd"),
    ("status", 15, None),
    ("open", 11, "#,##0.0000"),
    ("high", 11, "#,##0.0000"),
    ("low", 11, "#,##0.0000"),
    ("close", 11, "#,##0.0000"),
    ("volume", 14, "#,##0"),
    ("dividend", 10, "#,##0.0000"),
    ("daily_total_return", 18, "0.0000%"),
    ("sma_20", 12, "#,##0.0000"),
    ("sma_50", 12, "#,##0.0000"),
    ("vol_20d_annualised", 19, "0.00%"),
    ("available_time_utc", 26, None),
    ("event_time_utc", 26, None),
]

LABEL_COLUMNS = [
    ("ticker", 10, None),
    ("decision_date", 14, "yyyy-mm-dd"),
    ("decision_time_utc", 26, None),
    ("horizon_trading_days", 20, "0"),
    ("y", 6, "0"),
    ("excess_log_return", 18, "0.000000"),
    ("excess_return_pct", 18, "0.0000%"),
    ("status", 28, None),
    ("usable", 9, None),
    ("benchmark", 19, None),
    ("contract_version", 17, None),
]

SUMMARY_COLUMNS = [
    ("ticker", 10, None),
    ("bars", 8, "#,##0"),
    ("first_date", 12, None),
    ("last_date", 12, None),
    ("last_close", 12, "#,##0.0000"),
    ("usable_returns", 15, "#,##0"),
    ("gap_rows", 10, "#,##0"),
    ("labels_total", 13, "#,##0"),
    ("labels_usable", 14, "#,##0"),
    ("labels_unresolved", 18, "#,##0"),
    ("base_rate_y1", 13, "0.00%"),
    ("vintage_id", 20, None),
    ("source_file", 46, None),
    ("ingested_time", 26, None),
    ("source", 26, None),
]


def _as_date(value: Any):
    """ISO date string -> real Excel date, so sorting and charting behave."""
    if isinstance(value, str) and len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value


def _sheet_name(prefix: str, ticker: str) -> str:
    clean = "".join(c for c in ticker if c not in "[]:*?/\\")
    return f"{prefix}{clean}"[:31]


def _write_header(ws, columns) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    fill = PatternFill("solid", fgColor=HEADER_FILL)
    font = Font(bold=True, color="FFFFFF")
    for idx, (name, width, _fmt) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=idx, value=name)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = width
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 28


def _finish(ws, columns, n_rows: int) -> None:
    if n_rows:
        last_col = ws.cell(row=1, column=len(columns)).column_letter
        ws.auto_filter.ref = f"A1:{last_col}{n_rows + 1}"
    for idx, (_name, _width, fmt) in enumerate(columns, start=1):
        if not fmt:
            continue
        letter = ws.cell(row=1, column=idx).column_letter
        for row in range(2, n_rows + 2):
            ws[f"{letter}{row}"].number_format = fmt


def _write_readme(ws, data: dict[str, Any]) -> None:
    from openpyxl.styles import Alignment, Font

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 104

    lines: list[tuple[str, str]] = [
        ("MoneyPrinter", "Point-in-time market data and label export"),
        ("Generated (UTC)", data["generated_utc"].isoformat(timespec="seconds")),
        ("Data store", data["data_dir"]),
        ("Label contract", f"v{LABEL_CONTRACT_VERSION}"),
        ("", ""),
        ("READ THIS FIRST", ""),
        ("Paper/simulation only",
         "Research output. Not financial advice, not a recommendation, and no live order "
         "path exists anywhere in this project."),
        ("Nothing is filled in",
         "Missing bars are left missing. They break the return chain instead of being "
         "bridged, and they turn the affected labels unresolved. A blank cell is a real "
         "gap in the data, not a rendering artefact."),
        ("Point-in-time columns",
         "available_time_utc is the only timestamp a backtest may filter on. It is the "
         "morning AFTER the session, not the session's own close - a daily bar for date D "
         "is not consumable at 15:45 ET on D."),
        ("The Labels sheet is the answer key",
         "Labels are forward-looking by construction. Correct for fitting and scoring, "
         "never as an input feature. Everything else in this workbook is knowable in "
         "real time; the Labels sheet is not."),
        ("", ""),
        ("SHEETS", ""),
        ("Summary", "One row per ticker: coverage, gap count, and the label base rate."),
        ("Bars_<TICKER>",
         "Raw OHLCV, dividends, daily TOTAL return (includes distributions, computed from "
         "raw closes rather than vendor-adjusted ones), and both PIT timestamps."),
        ("Labels",
         f"Binary sign of the {HORIZON_TRADING_DAYS}-trading-day forward log excess total "
         f"return vs {BENCHMARK}. Decision clock is 15:45 ET on the decision date; the "
         "label is measured from the 16:00 close that follows it. The 15-minute gap is "
         "deliberate - the model cannot consume the price it is scored against."),
        ("", ""),
        ("COLUMNS YOU CAN RETUNE", ""),
        ("sma_20 / sma_50",
         "Live Excel formulas, not pasted values. Widen or narrow the AVERAGE() range and "
         "the column recalculates. Both look backwards only, so they stay honest."),
        ("vol_20d_annualised",
         "STDEV of daily total return over the trailing 20 rows, times SQRT(252). Change "
         "252 if you want a different annualisation convention."),
        ("excess_return_pct",
         "=EXP(excess_log_return)-1, so you can read the target in percent instead of logs."),
        ("", ""),
        ("LABEL STATUS VALUES", ""),
        ("OK", "Resolved. y is 1 or 0 and is safe to train or score against."),
        ("INSUFFICIENT_FORWARD_BARS",
         "The 5-day outcome has not happened yet, or the file ends first. Expect this on "
         "the last few dates of every ticker. It means 'not known yet', not 'no signal'."),
        ("RETURN_GAP_UNRESOLVED",
         "A missing session sits inside the forward window, for this ticker or for the "
         "benchmark. Failed closed rather than bridged."),
        ("CORPORATE_ACTION_UNRESOLVED",
         "An unresolved split/merger makes the return series untrustworthy."),
        ("", ""),
        ("REGENERATING THIS FILE", ""),
        ("1. Fetch", "python claude/app/mp_v01/fetch_data.py --tickers SPY,QQQ,MSFT"),
        ("2. Export", "python excel_report.py"),
        ("or", "python gui.py, then Fetch data -> Build Excel workbook"),
        ("Note", "Every export writes a NEW timestamped file. Your edits to an existing "
                 "workbook are never overwritten."),
        ("", ""),
        ("SOURCE FILES USED", ""),
    ]
    for ticker, path in sorted(data["files"].items()):
        lines.append((ticker, path))
    if not data["files"]:
        lines.append(("(none)", "The data store was empty. Fetch data first."))
    if not data["benchmark_present"]:
        lines.append(("", ""))
        lines.append(
            (
                "BENCHMARK MISSING",
                f"{BENCHMARK} is not in the data store, so excess return vs {BENCHMARK} is "
                f"undefined and no labels were built for other tickers. Substituting a "
                f"different benchmark would change what the model is being asked to "
                f"predict, so nothing was substituted. Re-fetch including {BENCHMARK}.",
            )
        )

    bold = Font(bold=True)
    wrap = Alignment(vertical="top", wrap_text=True)
    for r, (left, right) in enumerate(lines, start=1):
        a = ws.cell(row=r, column=1, value=left)
        b = ws.cell(row=r, column=2, value=right)
        a.alignment = wrap
        b.alignment = wrap
        if left and not right:
            a.font = Font(bold=True, size=12)
        elif left:
            a.font = bold


def _write_summary(ws, summaries: list[dict[str, Any]]) -> None:
    _write_header(ws, SUMMARY_COLUMNS)
    for r, row in enumerate(summaries, start=2):
        for c, (name, _w, _f) in enumerate(SUMMARY_COLUMNS, start=1):
            ws.cell(row=r, column=c, value=row.get(name))
    _finish(ws, SUMMARY_COLUMNS, len(summaries))


def _write_bars(ws, rows: list[dict[str, Any]]) -> None:
    _write_header(ws, BAR_COLUMNS)
    for r, row in enumerate(rows, start=2):
        ws.cell(row=r, column=1, value=_as_date(row.get("date")))
        ws.cell(row=r, column=2, value=row.get("status", "UNKNOWN"))
        ws.cell(row=r, column=3, value=row.get("open"))
        ws.cell(row=r, column=4, value=row.get("high"))
        ws.cell(row=r, column=5, value=row.get("low"))
        ws.cell(row=r, column=6, value=row.get("close"))
        ws.cell(row=r, column=7, value=row.get("volume"))
        ws.cell(row=r, column=8, value=row.get("dividend"))
        ws.cell(row=r, column=9, value=row.get("daily_total_return"))
        # Live formulas rather than baked values: the point of putting this in
        # Excel is to be able to change the window and see the effect.
        if r >= 21:
            ws.cell(row=r, column=10,
                    value=f'=IF(COUNT(F{r-19}:F{r})<20,"",AVERAGE(F{r-19}:F{r}))')
            ws.cell(row=r, column=12,
                    value=f'=IF(COUNT(I{r-19}:I{r})<20,"",STDEV(I{r-19}:I{r})*SQRT(252))')
        if r >= 51:
            ws.cell(row=r, column=11,
                    value=f'=IF(COUNT(F{r-49}:F{r})<50,"",AVERAGE(F{r-49}:F{r}))')
        ws.cell(row=r, column=13, value=row.get("available_time"))
        ws.cell(row=r, column=14, value=row.get("event_time"))
    _finish(ws, BAR_COLUMNS, len(rows))


def _write_labels(ws, labels: list[dict[str, Any]]) -> None:
    _write_header(ws, LABEL_COLUMNS)
    for r, row in enumerate(labels, start=2):
        ws.cell(row=r, column=1, value=row["ticker"])
        ws.cell(row=r, column=2, value=_as_date(row["decision_date"]))
        ws.cell(row=r, column=3, value=row["decision_time_utc"])
        ws.cell(row=r, column=4, value=row["horizon_trading_days"])
        ws.cell(row=r, column=5, value=row["y"])
        ws.cell(row=r, column=6, value=row["excess_log_return"])
        ws.cell(row=r, column=7, value=f'=IF(F{r}="","",EXP(F{r})-1)')
        ws.cell(row=r, column=8, value=row["status"])
        ws.cell(row=r, column=9, value=bool(row["usable"]))
        ws.cell(row=r, column=10, value=row["benchmark"])
        ws.cell(row=r, column=11, value=row["contract_version"])
    _finish(ws, LABEL_COLUMNS, len(labels))


def write_workbook(data: dict[str, Any], out_path: Path) -> Path:
    """Render collected data to .xlsx. Requires openpyxl; nothing else does."""
    try:
        from openpyxl import Workbook
    except ImportError as e:  # pragma: no cover - depends on the local machine
        raise SystemExit(
            "This step needs openpyxl to write .xlsx files.\n"
            "    pip install openpyxl\n"
            f"(import failed: {e})"
        )

    wb = Workbook()
    _write_readme(wb.active, data)
    wb.active.title = "README"

    _write_summary(wb.create_sheet("Summary"), data["summaries"])

    for ticker in sorted(data["rows"]):
        _write_bars(wb.create_sheet(_sheet_name("Bars_", ticker)), data["rows"][ticker])

    all_labels: list[dict[str, Any]] = []
    for ticker in sorted(data["labels"]):
        all_labels.extend(data["labels"][ticker])
    _write_labels(wb.create_sheet("Labels"), all_labels)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def default_out_path(out_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return out_dir / f"moneyprinter_{stamp}.xlsx"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                    help="point-in-time store written by fetch_data.py")
    ap.add_argument("--out", default=None,
                    help="output .xlsx path (default: excel_out/moneyprinter_<timestamp>.xlsx)")
    ap.add_argument("--tickers", default=None,
                    help="comma-separated subset; default is everything in the store")
    a = ap.parse_args(argv)

    data_dir = Path(a.data_dir).expanduser().resolve()
    only = a.tickers.split(",") if a.tickers else None

    print("=" * 70)
    print("MONEY PRINTER - Excel export")
    print("=" * 70)
    print(f"Data store : {data_dir}")

    if not (data_dir / "bars").is_dir():
        print(f"\nNo bars directory at {data_dir / 'bars'}.")
        print("Fetch some data first:")
        print("    python claude/app/mp_v01/fetch_data.py --tickers SPY,QQQ,MSFT")
        return 1

    data = collect(data_dir, only)
    if not data["rows"]:
        print("\nThe data store has no bar files matching that selection.")
        print("Fetch some data first:")
        print("    python claude/app/mp_v01/fetch_data.py --tickers SPY,QQQ,MSFT")
        return 1

    for s in data["summaries"]:
        base = f"{s['base_rate_y1']:.1%}" if s["base_rate_y1"] is not None else "n/a"
        print(f"  {s['ticker']:<8} {s['bars']:>6} bars  {s['first_date']} -> {s['last_date']}"
              f"   labels {s['labels_usable']}/{s['labels_total']} usable   base rate {base}")

    if not data["benchmark_present"]:
        print(f"\n  WARNING: {BENCHMARK} is not in the store. Excess return vs {BENCHMARK}")
        print(f"  is undefined without it, so no labels were built for the other tickers.")
        print(f"  Nothing was substituted. Re-fetch including {BENCHMARK}.")

    out_path = Path(a.out).expanduser() if a.out else default_out_path(DEFAULT_OUT_DIR)
    written = write_workbook(data, out_path.resolve())

    print(f"\nWorkbook written: {written}")
    print("Every export is a new timestamped file, so edits you make are never overwritten.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
