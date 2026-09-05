#!/usr/bin/env python3
"""
MoneyPrinter desktop GUI - fetch, export, pick, score, backtest, read.

    python gui.py

Numbered buttons run the workflow in order; the menu bar carries the rest. The
console echoes the exact command each button runs, so anything you can do here
you can also do from a terminal.

TWO OUTPUTS, TWO JOBS. The Excel workbook is the AUDIT TRAIL - every bar, label
and Greek, in a form you can sort and check the arithmetic of. The dashboard is
the READING SURFACE - the picks, why each one was proposed, and whether the
signal behind them has ever been shown to work. Use the workbook to check the
app; use the dashboard to read it.

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
import webbrowser
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
DIAGNOSE_SCRIPT = HERE / "diagnose.py"
RESOLVE_SCRIPT = HERE / "resolve_picks.py"
BACKTEST_SCRIPT = HERE / "backtest.py"
BACKTESTS_DIR = HERE / "backtests"
DASHBOARD_SCRIPT = HERE / "dashboard.py"
DASHBOARD_FILE = HERE / "dashboard.html"

# Everything a first run needs. Kept here rather than in a document so the
# "Install required packages" button and the docs cannot drift apart.
REQUIRED_PACKAGES = ["yfinance", "openpyxl", "tzdata"]
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
        self._pending_dashboard: Path | None = None
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
        self._build_menu()

        head = ttk.Frame(self, padding=(12, 10, 12, 0))
        head.pack(fill=tk.X)
        ttk.Label(head, text="MoneyPrinter", font=("Segoe UI", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(
            head,
            text="Fetch point-in-time market data, price the option chain, and log frozen "
                 "paper picks. Paper/simulation research only — nothing here places an order.",
            foreground="#555555", wraplength=980, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 8))

        # --- setup: the two things that used to require a terminal ----------
        setup = ttk.LabelFrame(self, text=" Setup ", padding=8)
        setup.pack(fill=tk.X, padx=12, pady=(0, 8))
        self.install_btn = ttk.Button(setup, text="Install required packages",
                                      command=self.install_packages)
        self.install_btn.pack(side=tk.LEFT)
        self.diag_btn = ttk.Button(setup, text="Check setup", command=self.check_setup)
        self.diag_btn.pack(side=tk.LEFT, padx=6)
        ttk.Label(setup, text="Run these once, or any time something looks wrong.",
                  foreground="#777777").pack(side=tk.LEFT, padx=8)

        # --- what to fetch --------------------------------------------------
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
        ttk.Checkbutton(row, text="also snapshot option chains (needed for Greeks and picks)",
                        variable=self.chains_var).pack(side=tk.LEFT)

        ttk.Label(
            box,
            text=f"Keep {BENCHMARK} in the list — the label is excess return vs {BENCHMARK}, "
                 f"so without it no labels can be built for anything else.",
            foreground="#777777",
        ).pack(anchor=tk.W, pady=(6, 0))

        # --- the workflow, in order -----------------------------------------
        steps = ttk.Frame(self, padding=(12, 0))
        steps.pack(fill=tk.X)
        self.fetch_btn = ttk.Button(steps, text="1 · Fetch market data", command=self.fetch_data)
        self.fetch_btn.pack(side=tk.LEFT)
        self.export_btn = ttk.Button(steps, text="2 · Build Excel workbook",
                                     command=self.export_excel)
        self.export_btn.pack(side=tk.LEFT, padx=6)
        self.picks_btn = ttk.Button(steps, text="3 · Generate paper picks",
                                    command=self.generate_picks)
        self.picks_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.score_btn = ttk.Button(steps, text="4 · Score past picks",
                                    command=self.score_picks)
        self.score_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.backtest_btn = ttk.Button(steps, text="5 · Backtest the signal",
                                       command=self.run_backtest)
        self.backtest_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.dash_btn = ttk.Button(steps, text="View dashboard",
                                   command=self.open_dashboard)
        self.dash_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(steps, text="Open output folder", command=self.open_output).pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(steps, text="Stop", command=self.stop_running,
                                   state=tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT)

        out_row = ttk.Frame(self, padding=(12, 8))
        out_row.pack(fill=tk.X)
        ttk.Label(out_row, text="Workbooks go to").pack(side=tk.LEFT)
        ttk.Entry(out_row, textvariable=self.outdir_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(out_row, text="Change…", command=self.choose_output).pack(side=tk.LEFT)

        self._job_buttons = (self.install_btn, self.diag_btn, self.fetch_btn,
                             self.export_btn, self.picks_btn, self.score_btn)

        # --- console --------------------------------------------------------
        con = ttk.Frame(self, padding=(12, 0))
        con.pack(fill=tk.BOTH, expand=True)
        bar = ttk.Frame(con)
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="Console", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        ttk.Label(bar, text="   every command this app runs is echoed here",
                  foreground="#777777").pack(side=tk.LEFT)
        self.elapsed_label = ttk.Label(bar, text="", foreground="#777777")
        self.elapsed_label.pack(side=tk.RIGHT)
        ttk.Button(bar, text="Clear", command=self.clear_console).pack(side=tk.RIGHT, padx=6)

        self.text = scrolledtext.ScrolledText(con, wrap=tk.WORD, font=("Consolas", 9),
                                              height=16, background="#FBFBFB")
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

    def _build_menu(self) -> None:
        """Menu bar carrying everything, including the rarely-used items.

        The buttons cover the ordinary path; this is where the occasional and
        the development-only things live, so the main window stays legible.
        """
        menubar = tk.Menu(self)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Open output folder", command=self.open_output)
        m_file.add_command(label="Change output folder…", command=self.choose_output)
        m_file.add_separator()
        m_file.add_command(label="Open the picks folder", command=self.open_picks)
        m_file.add_command(label="Open the backtests folder", command=self.open_backtests)
        m_file.add_separator()
        m_file.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=m_file)

        m_run = tk.Menu(menubar, tearoff=0)
        m_run.add_command(label="Install required packages", command=self.install_packages)
        m_run.add_command(label="Check setup", command=self.check_setup)
        m_run.add_separator()
        m_run.add_command(label="1 · Fetch market data", command=self.fetch_data)
        m_run.add_command(label="2 · Build Excel workbook", command=self.export_excel)
        m_run.add_command(label="3 · Generate paper picks", command=self.generate_picks)
        m_run.add_command(label="4 · Score past picks", command=self.score_picks)
        m_run.add_command(label="5 · Backtest the signal", command=self.run_backtest)
        m_run.add_command(label="Build and open the dashboard", command=self.open_dashboard)
        m_run.add_separator()
        m_run.add_command(label="Score a specific pick file…", command=self.score_picks_choose)
        m_run.add_command(label="Run the test suite", command=self.run_tests)
        m_run.add_separator()
        m_run.add_command(label="Market Intelligence Engine (development only)",
                          command=self.run_mie)
        menubar.add_cascade(label="Run", menu=m_run)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="What each button does", command=self.show_help)
        menubar.add_cascade(label="Help", menu=m_help)

        self.config(menu=menubar)

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

        if code == 0 and self._pending_dashboard is not None:
            page = self._pending_dashboard
            self._set_status(f"Dashboard ready — {page.name}", "#0B7A28")
            self._log(f"\nOpening {page} in your browser.\n", "success")
            try:
                webbrowser.open(page.as_uri())
            except Exception as e:      # a headless or locked-down desktop
                self._log(f"Could not open a browser ({e}). Open this file yourself:\n"
                          f"  {page}\n", "warning")
        elif code == 0 and self._pending_workbook is not None:
            self._last_workbook = self._pending_workbook
            self._set_status(f"Workbook ready — {self._last_workbook.name}", "#0B7A28")
            self._log(f"\nOpen it with '4 · Open output folder', or double-click:\n"
                      f"  {self._last_workbook}\n", "success")
        elif code == 0:
            self._set_status("Finished", "#0B7A28")
        else:
            self._set_status(f"Last run failed (exit {code}) — see console", "#C0281C")
        self._pending_workbook = None
        self._pending_dashboard = None
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

    def run_backtest(self) -> None:
        """Walk the signal forward through history, against a noise floor.

        This is the historical half of the question the picks raise. It asks
        whether the components behind them have EVER predicted the sign of
        5-trading-day forward excess return out of sample - and answers it
        against a permuted noise floor, so an accuracy number cannot be read
        without the thing that makes it readable.

        It is NOT a backtest of the options picks and cannot be made into one:
        Yahoo serves current chains only, so no historical chain exists to price
        a contract against. Both facts are printed on every run.
        """
        self._banner("Backtesting the signal")
        self._log(
            "Walk-forward over the bars already in the data store. No network, no fetch.\n\n"
            "WHAT IT MEASURES: whether a weighted blend of the components predicts the\n"
            "sign of 5-trading-day forward excess return versus SPY, out of sample.\n\n"
            "WHAT IT CANNOT: this is not an options backtest. No historical option chain\n"
            "exists in this data, so an options equity curve would be fabricated. The\n"
            "options layer is tested FORWARD, by buttons 3 and 4.\n\n"
            "Read the VERDICT lines, not the accuracy. Accuracy above the majority class\n"
            "means nothing until it also clears the noise floor.\n\n"
            "A few hundred permutations on a few years of bars takes under a minute.\n\n", "info")
        self._start([BACKTEST_SCRIPT, "--out-dir", BACKTESTS_DIR], "backtest.py", HERE)

    def open_dashboard(self) -> None:
        """Rebuild the dashboard from the newest files, then open it.

        It rebuilds every time rather than opening whatever is already on disk.
        A stale workbook has already cost this project one confusing bug report,
        and a dashboard is worse: it looks current no matter how old it is.
        """
        self._banner("Building the dashboard")
        self._log(
            "One self-contained .html file - every style, number and chart inlined.\n"
            "No CDN, no fonts to fetch, no server. Copy it to a machine with no network\n"
            "and it renders identically, which is what taking this offline needs.\n\n"
            "It reads the NEWEST pick file and the NEWEST backtest. If either section is\n"
            "empty, the page names the button that fills it.\n\n", "info")
        self._pending_dashboard = DASHBOARD_FILE
        if not self._start([DASHBOARD_SCRIPT, "--out", DASHBOARD_FILE,
                            "--picks-dir", PICKS_DIR, "--backtest-dir", BACKTESTS_DIR],
                           "dashboard.py", HERE):
            self._pending_dashboard = None

    def open_backtests(self) -> None:
        self._reveal(BACKTESTS_DIR)

    def install_packages(self) -> None:
        """Install what a first run needs, so no terminal is required.

        Uses `python -m pip` rather than a bare `pip`: on Windows those two can
        be different installs, and a package landing in the wrong interpreter
        looks exactly like a package that never installed.
        """
        self._banner("Installing required packages")
        self._log(
            f"Installing into the interpreter running this app:\n  {sys.executable}\n\n"
            f"  {', '.join(REQUIRED_PACKAGES)}\n\n"
            "yfinance fetches the data. openpyxl writes the workbooks. tzdata carries the\n"
            "timezone database Windows does not ship - without it the label's 15:45 ET\n"
            "decision clock cannot be built at all.\n\n"
            "Safe to run more than once; already-installed packages are left alone.\n\n",
            "info")
        self._start(["-m", "pip", "install", *REQUIRED_PACKAGES], "pip install", HERE)

    def check_setup(self) -> None:
        self._banner("Checking setup")
        self._log("Read-only. Reports which commit this copy is on, what the data store\n"
                  "holds, which pick files exist, and whether any workbook in the output\n"
                  "folder was built by older code.\n\n", "info")
        self._start([DIAGNOSE_SCRIPT], "diagnose.py", HERE)

    def _newest_pick_file(self) -> Path | None:
        try:
            files = sorted(PICKS_DIR.glob("picks_*.json"))
        except OSError:
            return None
        return files[-1] if files else None

    def score_picks(self) -> None:
        """Score the most recent frozen pick file."""
        newest = self._newest_pick_file()
        if newest is None:
            messagebox.showinfo(
                "No picks yet",
                "There are no frozen pick files to score.\n\n"
                "Run '3 · Generate paper picks' first. Scoring reads a file that was "
                "frozen earlier and checks what actually happened since.")
            return
        self._run_resolver(newest)

    def score_picks_choose(self) -> None:
        """Score a pick file the user chooses, rather than the newest."""
        try:
            PICKS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        chosen = filedialog.askopenfilename(
            initialdir=str(PICKS_DIR), title="Which frozen pick file?",
            filetypes=[("Frozen picks", "picks_*.json"), ("All files", "*.*")])
        if chosen:
            self._run_resolver(Path(chosen))

    def _run_resolver(self, pick_file: Path) -> None:
        self._banner(f"Scoring {pick_file.name}")
        self._log(
            "Re-hashes the picks before anything else. If the file was edited after it\n"
            "was frozen the digest will not match and scoring stops - that check is why\n"
            "a forward record is worth more than a backtest.\n\n"
            "Positions are walked day by day and closed on the first pre-registered rule\n"
            "that fires: profit target, stop loss, the 21-DTE floor, or the 5-day time\n"
            "stop if none did.\n\n", "info")
        self._start([RESOLVE_SCRIPT, pick_file], "resolve_picks.py", HERE)

    def show_help(self) -> None:
        """What every control does, in the app rather than in a document."""
        win = tk.Toplevel(self)
        win.title("What each button does")
        win.geometry("760x620")
        win.transient(self)

        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Segoe UI", 10),
                                        padx=14, pady=12)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.tag_configure("h", font=("Segoe UI", 11, "bold"), spacing1=10, spacing3=4)
        txt.tag_configure("note", foreground="#8A5A00")

        for tag, body in [
            ("h", "SETUP — run once"),
            (None, "Install required packages — installs yfinance, openpyxl and tzdata into "
                   "the interpreter this app is running on. Safe to repeat. tzdata is not "
                   "optional on Windows: it carries the timezone database Windows omits, and "
                   "without it the label's 15:45 ET decision clock cannot be built.\n\n"
                   "Check setup — a read-only report: which commit this copy is on, whether "
                   "each feature is present, what the data store holds, which pick files "
                   "exist, and whether any workbook in the output folder was built by older "
                   "code. Start here whenever something looks wrong."),

            ("h", "THE WORKFLOW"),
            (None, "1 · Fetch market data — downloads daily bars from Yahoo for the tickers "
                   "listed above. Every run writes a new immutable file and overwrites "
                   "nothing.\n\n"
                   "Tick 'also snapshot option chains' before fetching if you want Greeks or "
                   "picks. Yahoo has no historical chains, so a daily snapshot is the only "
                   "way to accumulate options history — and without a chain there is nothing "
                   "to compute Greeks from or choose a contract out of.\n\n"
                   "2 · Build Excel workbook — turns whatever is in the data store into a "
                   "workbook: bars, the label target, the option chain with Greeks, and the "
                   "accumulated pick history.\n\n"
                   "3 · Generate paper picks — scores every ticker under five weight "
                   "variants, proposes a contract for each that clears its conviction floor, "
                   "and freezes the result with a SHA-256 so it cannot be edited later. Then "
                   "rebuilds the workbook so the new picks join the history.\n\n"
                   "4 · Score past picks — takes the most recent frozen file and works out "
                   "what actually happened: whether the direction was right, and what "
                   "following the pre-registered exit rules would have returned.\n\n"
                   "5 · Backtest the signal — the historical half of the question. Walks the "
                   "components forward through every bar in the store, out of sample, and "
                   "measures them against a NOISE FLOOR: what the same procedure scores when "
                   "the labels are shuffled and the model refit. Also reports rank IC per "
                   "component — whether each one's ranking of instruments matches the ranking "
                   "of their forward returns, which is what justifies or retires a component "
                   "on its own. Needs no network.\n\n"
                   "View dashboard — rebuilds a single self-contained .html page and opens "
                   "it: the picks with their full rationale, then the backtest evidence. It "
                   "rebuilds every time rather than opening what is already on disk, because "
                   "a stale page looks current no matter how old it is."),

            ("h", "THE WORKBOOK VERSUS THE DASHBOARD"),
            (None, "They are not two views of the same thing and neither replaces the other.\n\n"
                   "The Excel workbook is the AUDIT TRAIL. Every bar, every label, every "
                   "Greek, every pick, in a form you can sort, pivot and check the arithmetic "
                   "of. Use it to verify the app rather than trust it.\n\n"
                   "The dashboard is the READING SURFACE. What the picks are, why each was "
                   "proposed, and whether the signal behind them has ever been shown to work. "
                   "One .html file with nothing external in it, so it works offline."),

            ("h", "WHERE THINGS GO"),
            (None, "Workbooks go to the folder shown above; every export is a new timestamped "
                   "file, so nothing you have edited is ever overwritten. Open the newest.\n\n"
                   "Frozen picks go to the picks folder, and backtest results to the "
                   "backtests folder. Commit the picks folder to git — it is the forward "
                   "record, and unlike the data store it cannot be regenerated. The "
                   "workbook's pick history is only a view over those files.\n\n"
                   "The dashboard is written to dashboard.html beside the app."),

            ("h", "IN THE MENU"),
            (None, "Run → Score a specific pick file… — score an older file instead of the "
                   "newest.\n\n"
                   "Run → Run the test suite — no network and no market data needed. "
                   "Worth running after an update.\n\n"
                   "Run → Market Intelligence Engine — development only. Its output is "
                   "unvalidated, it is not point-in-time correct, and its news input is "
                   "synthetic. Do not read anything into what it prints."),

            ("h", "WHAT THIS IS NOT"),
            ("note", "Paper and simulation only. No part of this project places an order, and "
                     "there is no code path that could.\n\n"
                     "No component in use has a measured relationship to future returns. The "
                     "risk gate therefore refuses every pick — it reads PASS, meaning do "
                     "nothing — and each pick records exactly what the gate was not told. "
                     "The picks are hypotheses being logged so they can eventually be "
                     "measured. They are not recommendations, and a run of good ones would "
                     "not yet be evidence of anything."),
        ]:
            txt.insert(tk.END, body + "\n", tag or "")
        txt.configure(state=tk.DISABLED)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))

    def open_picks(self) -> None:
        self._reveal(PICKS_DIR)

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
        self._reveal(self.out_dir(), self._last_workbook)

    def _reveal(self, out_dir: Path, select: Path | None = None) -> None:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Open folder", f"Cannot create {out_dir}:\n{e}")
            return
        target = select if (select and select.exists()) else None
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
