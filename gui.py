#!/usr/bin/env python3
"""
MoneyPrinter desktop GUI - fetch market data, turn it into an Excel workbook.

    python gui.py

Three buttons, in order: fetch, export, open the folder. Everything else is
tucked under Advanced. The console shows exactly which command ran, so anything
you can do here you can also do from a terminal.

Paper/simulation research only. Nothing in this project places an order.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

HERE = Path(__file__).resolve().parent
MP_V01_DIR = HERE / "claude" / "app" / "mp_v01"
FETCH_SCRIPT = MP_V01_DIR / "fetch_data.py"
EXPORT_SCRIPT = HERE / "excel_report.py"
MIE_SCRIPT = HERE / "market_intelligence_engine.py"
TEST_SCRIPT = HERE / "run_tests.py"
PICKS_SCRIPT = HERE / "generate_picks.py"
PICKS_DIR = HERE / "picks"
DEFAULT_OUT_DIR = HERE / "excel_out"
SETTINGS_FILE = Path.home() / ".moneyprinter_gui.json"

BENCHMARK = "SPY"          # labels are excess return vs this; see labels/contract.py


# ---------------------------------------------------------------------------
# Output classification
#
# Deliberately narrow. An earlier version coloured any line containing "pass"
# green, which painted the risk gate's PASS verdict - meaning "do NOT trade" -
# as if it were good news. Only explicit test markers count.
# ---------------------------------------------------------------------------

def classify(line: str) -> str:
    s = line.strip()
    low = s.lower()
    if s.startswith("$ "):
        return "command"
    if s.startswith("<process exited"):
        return "info"
    if "passed," in low and "failed" in low:
        return "success" if " 0 failed" in low else "error"
    if ("traceback" in low or low.startswith("error") or "FAILED:" in s
            or s.startswith("FAIL") or s.startswith("!!")
            or "STEP(S) FAILED" in s or "✗" in s or "❌" in s):
        return "error"
    if s.startswith("PASS") or s.startswith("✓") or "ALL GREEN" in s or "✅" in s:
        return "success"
    if low.startswith("warning") or "⚠" in s:
        return "warning"
    return "normal"


class SubprocessRunner(threading.Thread):
    """Runs one python script, streaming its output into a queue."""

    def __init__(self, args: list[str], cwd: Path, out_q: queue.Queue):
        super().__init__(daemon=True)
        self.args = args
        self.cwd = cwd
        self.out_q = out_q
        self.proc: subprocess.Popen | None = None

    def run(self) -> None:
        cmd = [sys.executable] + [str(a) for a in self.args]
        try:
            self.out_q.put(("command", f"$ {' '.join(cmd)}\n"))
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
            )
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self.out_q.put((classify(line), line))
            self.proc.wait()
            self.out_q.put(("done", self.proc.returncode))
        except Exception:
            self.out_q.put(("error", traceback.format_exc()))
            self.out_q.put(("done", 1))

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()


class MoneyPrinterGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MoneyPrinter — market data to Excel")
        self.geometry("1020x720")
        self.minsize(860, 560)

        self._runner: SubprocessRunner | None = None
        self._start_time: float | None = None
        self._pending_workbook: Path | None = None
        self._last_workbook: Path | None = None
        self._out_q: queue.Queue = queue.Queue()

        saved = self._load_settings()
        self.tickers_var = tk.StringVar(value=saved.get("tickers", "SPY,QQQ,MSFT"))
        self.start_var = tk.StringVar(value=saved.get("start", "2019-01-01"))
        self.end_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.chains_var = tk.BooleanVar(value=bool(saved.get("chains", False)))
        self.outdir_var = tk.StringVar(value=saved.get("outdir", str(DEFAULT_OUT_DIR)))
        self.mie_tickers_var = tk.StringVar(value=saved.get("mie_tickers", "AAPL,MSFT,GOOGL"))

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()

        if not MP_V01_DIR.is_dir():
            self._log(
                f"Cannot find the pipeline at {MP_V01_DIR}.\n"
                "gui.py expects to sit in the repository root, next to the 'claude' "
                "folder. Move it back, or edit MP_V01_DIR at the top of this file.\n",
                "error",
            )

    # -- layout ------------------------------------------------------------

    def _build_ui(self) -> None:
        self._setup_tags()

        head = ttk.Frame(self, padding=(12, 10, 12, 0))
        head.pack(fill=tk.X)
        ttk.Label(head, text="MoneyPrinter", font=("Segoe UI", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(
            head,
            text="Fetch point-in-time market data, then export it to a workbook you "
                 "can work in. Paper/simulation research only — nothing here places an order.",
            foreground="#555555",
            wraplength=960,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 8))

        # --- step 1 inputs -------------------------------------------------
        box = ttk.LabelFrame(self, text=" What to fetch ", padding=10)
        box.pack(fill=tk.X, padx=12, pady=(0, 8))

        row = ttk.Frame(box)
        row.pack(fill=tk.X)
        ttk.Label(row, text="Tickers").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.tickers_var, width=26).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(row, text="Start").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.start_var, width=12).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(row, text="End").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.end_var, width=12).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Checkbutton(row, text="also snapshot today's option chains",
                        variable=self.chains_var).pack(side=tk.LEFT)

        ttk.Label(
            box,
            text=f"Keep {BENCHMARK} in the list — the label is excess return vs {BENCHMARK}, "
                 f"so without it no labels can be built for anything else.  Option chains add "
                 f"the Greeks sheets; Yahoo does not publish Greeks, so they are computed.",
            foreground="#777777",
        ).pack(anchor=tk.W, pady=(6, 0))

        # --- the three steps ----------------------------------------------
        steps = ttk.Frame(self, padding=(12, 0))
        steps.pack(fill=tk.X)
        self.fetch_btn = ttk.Button(steps, text="1 · Fetch market data", command=self.fetch_data)
        self.fetch_btn.pack(side=tk.LEFT)
        self.export_btn = ttk.Button(steps, text="2 · Build Excel workbook", command=self.export_excel)
        self.export_btn.pack(side=tk.LEFT, padx=6)
        self.picks_btn = ttk.Button(steps, text="3 · Generate paper picks",
                                    command=self.generate_picks)
        self.picks_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(steps, text="4 · Open output folder", command=self.open_output).pack(side=tk.LEFT)

        out_row = ttk.Frame(self, padding=(12, 8))
        out_row.pack(fill=tk.X)
        ttk.Label(out_row, text="Workbooks go to").pack(side=tk.LEFT)
        ttk.Entry(out_row, textvariable=self.outdir_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(out_row, text="Change…", command=self.choose_output).pack(side=tk.LEFT)

        # --- advanced -------------------------------------------------------
        adv = ttk.LabelFrame(self, text=" Advanced ", padding=8)
        adv.pack(fill=tk.X, padx=12, pady=(0, 8))
        self.tests_btn = ttk.Button(adv, text="Run test suite", command=self.run_tests)
        self.tests_btn.pack(side=tk.LEFT)
        ttk.Label(adv, text="   MIE tickers").pack(side=tk.LEFT)
        ttk.Entry(adv, textvariable=self.mie_tickers_var, width=20).pack(side=tk.LEFT, padx=6)
        self.mie_btn = ttk.Button(adv, text="Run MIE (dev only)", command=self.run_mie)
        self.mie_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(adv, text="Stop", command=self.stop_running, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT)

        self._job_buttons = (self.fetch_btn, self.export_btn, self.picks_btn,
                             self.tests_btn, self.mie_btn)

        # --- console --------------------------------------------------------
        con = ttk.Frame(self, padding=(12, 0))
        con.pack(fill=tk.BOTH, expand=True)
        bar = ttk.Frame(con)
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="Console", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self.elapsed_label = ttk.Label(bar, text="", foreground="#777777")
        self.elapsed_label.pack(side=tk.RIGHT)
        ttk.Button(bar, text="Clear", command=self.clear_console).pack(side=tk.RIGHT, padx=6)

        self.text = scrolledtext.ScrolledText(con, wrap=tk.WORD, font=("Consolas", 9),
                                              height=18, background="#FBFBFB")
        self.text.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        self.text.configure(state=tk.DISABLED)
        for tag, cfg in self._tag_styles.items():
            self.text.tag_configure(tag, **cfg)

        # --- status ---------------------------------------------------------
        status = ttk.Frame(self)
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = ttk.Label(status, text="Ready", relief=tk.SUNKEN, anchor=tk.W, padding=4)
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=120)
        self.progress.pack(side=tk.RIGHT, padx=8, pady=4)

    def _setup_tags(self) -> None:
        self._tag_styles = {
            "success": {"foreground": "#0B7A28"},
            "error": {"foreground": "#C0281C"},
            "warning": {"foreground": "#B26B00"},
            "command": {"foreground": "#1F5FBF"},
            "info": {"foreground": "#777777"},
            "normal": {"foreground": "#1A1A1A"},
        }

    # -- small helpers -----------------------------------------------------

    def _log(self, s: str, tag: str = "normal") -> None:
        self.text.configure(state=tk.NORMAL)
        self.text.insert(tk.END, s, tag)
        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)

    def _banner(self, title: str, tag: str = "command") -> None:
        self._log("\n" + "─" * 78 + f"\n{title}\n" + "─" * 78 + "\n\n", tag)

    def clear_console(self) -> None:
        self.text.configure(state=tk.NORMAL)
        self.text.delete(1.0, tk.END)
        self.text.configure(state=tk.DISABLED)

    def _set_status(self, text: str, color: str = "black") -> None:
        self.status.config(text=text, foreground=color)

    def _busy(self, busy: bool) -> None:
        for b in self._job_buttons:
            b.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.stop_btn.config(state=tk.NORMAL if busy else tk.DISABLED)

    def out_dir(self) -> Path:
        return Path(self.outdir_var.get().strip() or DEFAULT_OUT_DIR).expanduser()

    def _tickers(self) -> list[str]:
        return [t.strip().upper() for t in self.tickers_var.get().split(",") if t.strip()]

    @staticmethod
    def _valid_date(s: str) -> bool:
        try:
            datetime.strptime(s.strip(), "%Y-%m-%d")
            return True
        except ValueError:
            return False

    # -- settings ----------------------------------------------------------

    def _load_settings(self) -> dict:
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_settings(self) -> None:
        try:
            SETTINGS_FILE.write_text(json.dumps({
                "tickers": self.tickers_var.get(),
                "start": self.start_var.get(),
                "chains": self.chains_var.get(),
                "outdir": self.outdir_var.get(),
                "mie_tickers": self.mie_tickers_var.get(),
            }, indent=2), encoding="utf-8")
        except Exception:
            pass          # a settings file we cannot write is not worth a dialog

    def _on_close(self) -> None:
        self._save_settings()
        if self._runner is not None and self._runner.is_alive():
            self._runner.stop()
        self.destroy()

    # -- job plumbing ------------------------------------------------------

    def _start(self, args: list, label: str, cwd: Path) -> bool:
        if self._runner is not None and self._runner.is_alive():
            messagebox.showinfo("Busy", "Something is already running. Wait for it, or press Stop.")
            return False
        self._set_status(f"Running {label}…")
        self._busy(True)
        self.progress.start(12)
        self._start_time = time.time()
        self._runner = SubprocessRunner(args, cwd, self._out_q)
        self._runner.start()
        return True

    def stop_running(self) -> None:
        if self._runner is not None and self._runner.is_alive():
            self._runner.stop()
            self._log("\nStop requested.\n", "warning")

    def _poll(self) -> None:
        try:
            while True:
                tag, payload = self._out_q.get_nowait()
                if tag == "done":
                    self._finish(int(payload))
                else:
                    self._log(payload, tag)
        except queue.Empty:
            pass

        if self._start_time is not None:
            elapsed = int(time.time() - self._start_time)
            self.elapsed_label.config(text=f"{elapsed // 60}m {elapsed % 60:02d}s")
        self.after(100, self._poll)

    def _finish(self, code: int) -> None:
        self._busy(False)
        self.progress.stop()
        self._start_time = None
        self._log(f"\n<process exited {code}>\n", "info")

        if code == 0 and self._pending_workbook is not None:
            self._last_workbook = self._pending_workbook
            self._set_status(f"Workbook ready — {self._last_workbook.name}", "#0B7A28")
            self._log(f"\nOpen it with '4 · Open output folder', or double-click:\n"
                      f"  {self._last_workbook}\n", "success")
        elif code == 0:
            self._set_status("Finished", "#0B7A28")
        else:
            self._set_status(f"Last run failed (exit {code}) — see console", "#C0281C")
        self._pending_workbook = None
        self._save_settings()

    # -- actions -----------------------------------------------------------

    def fetch_data(self) -> None:
        tickers = self._tickers()
        if not tickers:
            messagebox.showwarning("Fetch", "Enter at least one ticker, e.g. SPY,QQQ,MSFT.")
            return
        for name, value in (("Start", self.start_var.get()), ("End", self.end_var.get())):
            if not self._valid_date(value):
                messagebox.showwarning("Fetch", f"{name} date must look like 2019-01-01.")
                return
        if BENCHMARK not in tickers:
            proceed = messagebox.askyesno(
                "Benchmark missing",
                f"{BENCHMARK} is not in your ticker list.\n\n"
                f"Labels are the forward excess return vs {BENCHMARK}, so without it the "
                f"workbook will contain bars but no labels for these tickers.\n\n"
                f"Fetch anyway?",
            )
            if not proceed:
                return

        args = [FETCH_SCRIPT, "--tickers", ",".join(tickers),
                "--start", self.start_var.get().strip(), "--end", self.end_var.get().strip()]
        if self.chains_var.get():
            args.append("--chains")

        self._banner("Fetching daily bars from Yahoo (free, no API key)")
        self._log("Needs yfinance:  pip install yfinance\n"
                  "Each run writes a new immutable vintage; nothing is overwritten.\n\n", "info")
        self._start(args, "fetch_data.py", MP_V01_DIR)

    def export_excel(self) -> None:
        out_dir = self.out_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Output folder", f"Cannot create {out_dir}:\n{e}")
            return

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = out_dir / f"moneyprinter_{stamp}.xlsx"

        self._banner("Building the Excel workbook")
        self._log("Exports every ticker currently in the data store. Needs openpyxl:\n"
                  "  pip install openpyxl\n\n", "info")
        self._pending_workbook = target
        if not self._start([EXPORT_SCRIPT, "--out", target], "excel_report.py", HERE):
            self._pending_workbook = None

    def generate_picks(self) -> None:
        """Freeze a paper-pick list and render it to Excel.

        Two outputs on purpose: the JSON in picks/ is the hashed record and is
        what makes the forward log worth anything, and the workbook is the
        readable view of it. The workbook is rendered FROM the frozen file
        rather than derived alongside it, so the two cannot disagree.
        """
        out_dir = self.out_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Output folder", f"Cannot create {out_dir}:\n{e}")
            return

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = out_dir / f"moneyprinter_{stamp}.xlsx"

        self._banner("Generating paper picks")
        self._log(
            "Needs a fetch WITH option chains — tick the box in step 1 if you have not.\n\n"
            "Writes the hashed JSON record under picks\\, then rebuilds the workbook so\n"
            "Pick_History shows this run alongside every earlier one. That history comes\n"
            "from the files in picks\\, so commit them — they are the record, and unlike\n"
            "the data store they are not regenerable.\n\n"
            "These are hypotheses for forward measurement, not recommendations. The risk\n"
            "gate declines to approve any of them, and the workbook says why.\n\n", "info")
        self._pending_workbook = target
        args = [PICKS_SCRIPT, "--out-dir", PICKS_DIR, "--excel", target,
                "--decision-date", datetime.now().strftime("%Y-%m-%d")]
        if not self._start(args, "generate_picks.py", HERE):
            self._pending_workbook = None

    def run_tests(self) -> None:
        self._banner("Running every test suite (no network, no market data)")
        self._start([TEST_SCRIPT], "run_tests.py", HERE)

    def run_mie(self) -> None:
        tickers = [t.strip().upper() for t in self.mie_tickers_var.get().split(",") if t.strip()]
        if not tickers:
            messagebox.showwarning("MIE", "Enter at least one ticker, e.g. AAPL,MSFT.")
            return
        self._banner("MARKET INTELLIGENCE ENGINE — DEVELOPMENT ONLY", "warning")
        self._log("Unvalidated output. Not point-in-time correct, news input is synthetic.\n"
                  "See CODE_REVIEW_2026-08-13.md before believing any number it prints.\n\n",
                  "warning")
        # Passed as real arguments. This used to be generated by interpolating the
        # ticker string into a temp .py file written next to the repo root, which
        # broke on any unexpected character and left the file behind.
        self._start([MIE_SCRIPT, "--tickers", ",".join(tickers)], "market_intelligence_engine.py", HERE)

    def choose_output(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(self.out_dir().parent),
                                         title="Where should workbooks go?")
        if chosen:
            self.outdir_var.set(chosen)
            self._save_settings()

    def open_output(self) -> None:
        out_dir = self.out_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Open folder", f"Cannot create {out_dir}:\n{e}")
            return
        target = self._last_workbook if (
            self._last_workbook and self._last_workbook.exists()) else None
        try:
            if sys.platform.startswith("win"):
                if target:
                    # /select and the path must be a single argument.
                    # explorer exits non-zero even on success, so don't check.
                    subprocess.run(["explorer", f"/select,{target}"])
                else:
                    os.startfile(str(out_dir))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(target)] if target else ["open", str(out_dir)])
            else:
                subprocess.run(["xdg-open", str(out_dir)])
        except Exception as e:
            messagebox.showerror("Open folder", f"Could not open {out_dir}:\n{e}")


def main() -> int:
    MoneyPrinterGUI().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
