#!/usr/bin/env python3
"""
Answer "what am I actually running, and what did it produce?" in one command.

    python diagnose.py

Written after two rounds of confusion that both came down to the same thing:
a symptom was read from a file that a NEWER build no longer produces. Every
export writes a new timestamped workbook and none are ever deleted, so
excel_out/ accumulates - and double-clicking the wrong one shows you a bug
that was fixed weeks ago.

Reports, in order:
  1. which commit this working copy is on, and whether the features are in it
  2. what the data store holds (bars, and crucially whether chains were fetched)
  3. what frozen picks exist
  4. every workbook in excel_out/, newest first, with its sheets and whether it
     carries the Excel-repair defect

Read-only. Touches nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "claude" / "app" / "mp_v01" / "data_store"
EXCEL_DIR = HERE / "excel_out"
PICKS_DIR = HERE / "picks"

# Markers that prove a feature is present in THIS checkout, not just on GitHub.
FEATURE_MARKERS = [
    ("Option Greeks", HERE / "claude/app/mp_v01/src/options/greeks.py", None),
    ("Strategy layer", HERE / "claude/app/mp_v01/src/strategy/picks.py", None),
    ("Pick generator", HERE / "generate_picks.py", None),
    ("Pick resolver", HERE / "resolve_picks.py", None),
    ("Greeks in the export", HERE / "excel_report.py", "iv_solved"),
    ("Pick tabs in the export", HERE / "excel_report.py", "Pick_History"),
    ("Excel-repair fix", HERE / "excel_report.py", "def _text_cell"),
    ("Picks button in the GUI", HERE / "gui.py", "Generate paper picks"),
]


def rule(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(HERE), capture_output=True,
                              text=True, timeout=15).stdout.strip()
    except Exception as e:
        return f"(git unavailable: {e})"


def check_code() -> None:
    rule("1. THIS WORKING COPY")
    print(f"  Folder     : {HERE}")
    print(f"  Branch     : {git('rev-parse', '--abbrev-ref', 'HEAD') or '(unknown)'}")
    print(f"  Commit     : {git('log', '-1', '--format=%h  %ad  %s', '--date=short') or '(unknown)'}")
    dirty = git("status", "--porcelain")
    print(f"  Local edits: {'yes - ' + str(len(dirty.splitlines())) + ' file(s)' if dirty else 'none'}")

    print("\n  Features present in these files:")
    missing = []
    for label, path, needle in FEATURE_MARKERS:
        if not path.exists():
            ok = False
        elif needle is None:
            ok = True
        else:
            try:
                ok = needle in path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                ok = False
        print(f"    [{'x' if ok else ' '}] {label}")
        if not ok:
            missing.append(label)
    if missing:
        print("\n  Some features are NOT in this checkout. You are on an older commit,")
        print("  or on a branch without them. Fix with:")
        print("      git checkout main")
        print("      git pull")


def check_store() -> None:
    rule("2. DATA STORE")
    bars, chains = DATA_DIR / "bars", DATA_DIR / "chains"
    print(f"  {DATA_DIR}")

    bar_files = sorted(bars.glob("*.json")) if bars.is_dir() else []
    print(f"\n  Bars   : {len(bar_files)} file(s)")
    tickers: dict[str, str] = {}
    for p in bar_files:
        head, sep, vintage = p.stem.partition("__v")
        if sep:
            t = head.split("_")[0].upper()
            tickers[t] = max(tickers.get(t, ""), vintage)
    for t, v in sorted(tickers.items()):
        print(f"           {t:<8} newest vintage {v}")
    if not bar_files:
        print("           NONE. Fetch first - nothing downstream can work.")

    chain_files = sorted(chains.glob("*.json")) if chains.is_dir() else []
    print(f"\n  Chains : {len(chain_files)} file(s)")
    for p in chain_files[-6:]:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            print(f"           {doc.get('underlying','?'):<8} snapshot "
                  f"{str(doc.get('snapshot_time_utc'))[:10]}   "
                  f"{len(doc.get('contracts', []))} contracts")
        except (OSError, ValueError):
            print(f"           {p.name}  (unreadable)")
    if not chain_files:
        print("           NONE.")
        print("\n  >>> THIS IS WHY YOU HAVE NO GREEKS AND NO PICKS. <<<")
        print("      Greeks are computed from an option chain, and picks need one to")
        print("      choose a contract from. Bars alone cannot produce either.")
        print("      Fix: tick 'also snapshot today's option chains' in the GUI before")
        print("      Fetch, or run:")
        print("        python claude/app/mp_v01/fetch_data.py --tickers SPY,QQQ,MSFT --chains")


def check_picks() -> None:
    rule("3. FROZEN PICKS")
    files = sorted(PICKS_DIR.glob("picks_*.json")) if PICKS_DIR.is_dir() else []
    print(f"  {PICKS_DIR}\n  {len(files)} pick file(s)")
    for p in files[-10:]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            print(f"    {p.name:<44} {d.get('n_picks', '?')} picks, "
                  f"{d.get('n_abstentions', '?')} abstentions")
        except (OSError, ValueError):
            print(f"    {p.name:<44} (unreadable)")
    if not files:
        print("    NONE. Run the GUI's '3 - Generate paper picks', or:")
        print("      python generate_picks.py")


def check_workbooks() -> None:
    rule("4. WORKBOOKS IN excel_out/  (newest first)")
    if not EXCEL_DIR.is_dir():
        print(f"  No {EXCEL_DIR} yet.")
        return
    books = sorted(EXCEL_DIR.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not books:
        print(f"  No .xlsx files in {EXCEL_DIR}.")
        return

    print("  Every export writes a NEW file and deletes nothing, so old ones pile up.")
    print("  Open the newest. An older one shows you bugs already fixed.\n")

    for i, p in enumerate(books):
        when = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        tag = "  <-- NEWEST, open this one" if i == 0 else ""
        print(f"  {p.name:<40} {when}{tag}")
        try:
            with zipfile.ZipFile(p) as z:
                parts = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
                first = z.read("xl/worksheets/sheet1.xml").decode(errors="replace")
                bad = first.count("<f>")
            import openpyxl
            names = openpyxl.load_workbook(p, read_only=True).sheetnames
            print(f"      {len(parts)} sheets: {', '.join(names)}")
            has_opt = any(n.startswith("Options_") for n in names)
            has_pick = any(n.startswith("Pick_") for n in names)
            print(f"      Greeks/options sheets: {'yes' if has_opt else 'NO'}"
                  f"      pick sheets: {'yes' if has_pick else 'NO'}")
            if bad:
                print(f"      *** sheet1 ({names[0]}) carries {bad} stray formula(s). ***")
                print("      This is the 'Removed Records: Formula' repair prompt, and it was")
                print("      fixed in commit 963ce07. A workbook showing it was built by older")
                print("      code - regenerate rather than reopening this one.")
        except ImportError:
            print("      (install openpyxl to inspect sheet names: pip install openpyxl)")
        except Exception as e:
            print(f"      (could not inspect: {type(e).__name__}: {e})")


def main() -> int:
    print("=" * 74)
    print("MONEY PRINTER - environment diagnostic")
    print("=" * 74)
    print(f"Python {sys.version.split()[0]}")
    check_code()
    check_store()
    check_picks()
    check_workbooks()
    print(f"\n{'=' * 74}")
    print("Read-only. Nothing above was modified.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
