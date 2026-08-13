#!/usr/bin/env python3
"""
Enhanced MoneyPrinter GUI with live output streaming, better UX, and MIE support.

Features:
- Run tests (run_all.py) with live output streaming
- Fetch data with real-time progress
- Run Market Intelligence Engine with live metrics
- Browse data_store directories and view JSON files
- Console output with syntax highlighting for success/failure/warnings
- Better status indicators and progress tracking

Run from repo root:
  python gui.py
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

HERE = Path(__file__).resolve().parent
MP_V01_DIR = HERE / "claude" / "app" / "mp_v01"
DATA_DIR = MP_V01_DIR / "data_store"


class SubprocessRunner(threading.Thread):
    """Runs subprocess in background thread, pipes output to queue."""
    def __init__(self, cmd, cwd: Path | None = None, env: dict | None = None, out_q: queue.Queue | None = None):
        super().__init__(daemon=True)
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.out_q = out_q or queue.Queue()
        self.proc = None

    def run(self):
        try:
            full_cmd = [sys.executable] + list(self.cmd)
            self.out_q.put(("command", f"$ {' '.join(full_cmd)}\n"))
            self.proc = subprocess.Popen(
                full_cmd,
                cwd=str(self.cwd) if self.cwd is not None else None,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
            )
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                # Simple heuristics for coloring output
                if any(x in line.lower() for x in ["pass", "success", "✓", "✅"]):
                    self.out_q.put(("success", line))
                elif any(x in line.lower() for x in ["fail", "error", "✗", "❌"]):
                    self.out_q.put(("error", line))
                elif any(x in line.lower() for x in ["warning", "⚠️", "skip"]):
                    self.out_q.put(("warning", line))
                else:
                    self.out_q.put(("normal", line))
            self.proc.wait()
            self.out_q.put(("info", f"\n<process exited {self.proc.returncode}>\n"))
        except Exception:
            self.out_q.put(("error", traceback.format_exc()))
            self.out_q.put(("info", "\n<process exited 1>\n"))

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()


class MoneyPrinterGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MoneyPrinter — AI Trading Research")
        self.geometry("1400x800")
        
        # Configure text tags for colored output
        self._setup_text_tags()

        if not MP_V01_DIR.exists():
            messagebox.showerror(
                "MoneyPrinter GUI",
                f"Can't find the pipeline at:\n{MP_V01_DIR}\n\n"
                "This file expects to live at the repository root, next to the "
                "'claude' folder. If you moved it, move it back or update "
                "MP_V01_DIR at the top of gui.py.",
            )

        self._current_runner: SubprocessRunner | None = None
        self._start_time: float | None = None

        # ===== TOP FRAME: MAIN CONTROLS =====
        top_frame = ttk.Frame(self)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)

        # Title
        title = ttk.Label(top_frame, text="MoneyPrinter Research Pipeline", font=("Arial", 14, "bold"))
        title.pack(anchor=tk.W, pady=(0, 8))

        # ===== CONTROL BUTTONS =====
        ctrl = ttk.Frame(top_frame)
        ctrl.pack(fill=tk.X, pady=(0, 8))

        # Production system
        prod_frame = ttk.LabelFrame(ctrl, text="Production System (mp_v01)", padding=8)
        prod_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.run_tests_btn = ttk.Button(prod_frame, text="▶ Run All Tests (76)", command=self.run_tests)
        self.run_tests_btn.pack(side=tk.LEFT, padx=4)

        ttk.Label(prod_frame, text="Tickers:").pack(side=tk.LEFT, padx=(8, 0))
        self.tickers_var = tk.StringVar(value="SPY,QQQ,MSFT")
        self.tickers_entry = ttk.Entry(prod_frame, textvariable=self.tickers_var, width=18)
        self.tickers_entry.pack(side=tk.LEFT, padx=4)

        ttk.Label(prod_frame, text="Start:").pack(side=tk.LEFT, padx=(8, 0))
        self.start_var = tk.StringVar(value="2019-01-01")
        self.start_entry = ttk.Entry(prod_frame, textvariable=self.start_var, width=12)
        self.start_entry.pack(side=tk.LEFT, padx=4)

        ttk.Label(prod_frame, text="End:").pack(side=tk.LEFT, padx=(8, 0))
        self.end_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.end_entry = ttk.Entry(prod_frame, textvariable=self.end_var, width=12)
        self.end_entry.pack(side=tk.LEFT, padx=4)

        self.chains_var = tk.BooleanVar(value=False)
        self.chains_cb = ttk.Checkbutton(prod_frame, text="Options (--chains)", variable=self.chains_var)
        self.chains_cb.pack(side=tk.LEFT, padx=8)

        self.fetch_btn = ttk.Button(prod_frame, text="📥 Fetch Data", command=self.fetch_data)
        self.fetch_btn.pack(side=tk.LEFT, padx=4)

        # Development system
        dev_frame = ttk.LabelFrame(ctrl, text="Development (market_intelligence_engine)", padding=8)
        dev_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        ttk.Label(dev_frame, text="Tickers:").pack(side=tk.LEFT, padx=(0, 0))
        self.mie_tickers_var = tk.StringVar(value="AAPL,MSFT,GOOGL")
        self.mie_tickers_entry = ttk.Entry(dev_frame, textvariable=self.mie_tickers_var, width=18)
        self.mie_tickers_entry.pack(side=tk.LEFT, padx=4)

        self.mie_btn = ttk.Button(dev_frame, text="🧪 Run MIE (DEV ONLY)", command=self.run_mie)
        self.mie_btn.pack(side=tk.LEFT, padx=4)

        # Stop button
        self.stop_btn = ttk.Button(dev_frame, text="⏹ Stop", command=self.stop_running, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)

        self._job_buttons = (self.run_tests_btn, self.fetch_btn, self.mie_btn)

        # ===== MIDDLE FRAME: OUTPUT + BROWSER =====
        middle = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        middle.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # LEFT: Console output with syntax highlighting
        out_frame = ttk.Frame(middle)
        middle.add(out_frame, weight=3)

        out_label_frame = ttk.Frame(out_frame)
        out_label_frame.pack(fill=tk.X, pady=(0, 4))
        
        ttk.Label(out_label_frame, text="📟 Console Output", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        self.elapsed_label = ttk.Label(out_label_frame, text="", foreground="gray")
        self.elapsed_label.pack(side=tk.RIGHT)

        self.text = scrolledtext.ScrolledText(out_frame, wrap=tk.CHAR, font=("Courier", 9))
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.configure(state=tk.DISABLED)

        # RIGHT: Data store browser
        browse_frame = ttk.LabelFrame(middle, text="📂 Data Store Browser", padding=6)
        middle.add(browse_frame, weight=1)

        self.store_list = tk.Listbox(browse_frame, height=20, font=("Courier", 9))
        self.store_list.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.store_list.bind('<Double-Button-1>', lambda e: self.open_selected_file())

        btns = ttk.Frame(browse_frame)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="🔄 Refresh", command=self.refresh_store).pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Button(btns, text="👁 Open", command=self.open_selected_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="📂 Reveal", command=self.reveal_in_file_manager).pack(side=tk.LEFT, padx=2)

        # ===== BOTTOM: STATUS BAR =====
        status_frame = ttk.Frame(self)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.status = ttk.Label(status_frame, text="✓ Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.progress = ttk.Progressbar(status_frame, mode='indeterminate', length=100)
        self.progress.pack(side=tk.RIGHT, padx=8, pady=4)

        # Queue and poller
        self._out_q = queue.Queue()
        self._poll()

        # Initial refresh
        self.refresh_store()

    def _setup_text_tags(self):
        """Configure syntax highlighting for console output."""
        self.text_tags = {}
        
        # Define tag styles
        styles = {
            "success": {"foreground": "#00AA00", "font": ("Courier", 9)},
            "error": {"foreground": "#FF3333", "font": ("Courier", 9, "bold")},
            "warning": {"foreground": "#FF9900", "font": ("Courier", 9)},
            "command": {"foreground": "#0066FF", "font": ("Courier", 9, "bold")},
            "info": {"foreground": "#666666", "font": ("Courier", 9, "italic")},
            "normal": {"foreground": "#000000", "font": ("Courier", 9)},
        }
        
        self.text_tags = styles

    def _append_text(self, s: str, tag: str = "normal"):
        """Append colored text to console."""
        self.text.configure(state=tk.NORMAL)
        self.text.insert(tk.END, s, tag)
        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)

    def _set_status(self, text: str, color: str = "black", icon: str = "✓"):
        """Update status bar."""
        self.status.config(text=f"{icon} {text}", foreground=color)

    def _set_job_buttons_enabled(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        for b in self._job_buttons:
            b.config(state=state)
        self.stop_btn.config(state=tk.DISABLED if enabled else tk.NORMAL)

    def _start_runner(self, args, label: str, cwd=None):
        if self._current_runner is not None and self._current_runner.is_alive():
            messagebox.showinfo("Busy", "Another job is running. Stop it first or wait for it to finish.")
            return
        
        self._set_status(f"Running: {label} ...", icon="▶")
        self._set_job_buttons_enabled(False)
        self.progress.start()
        
        import time
        self._start_time = time.time()
        
        runner = SubprocessRunner(args, cwd=cwd or MP_V01_DIR, env=os.environ.copy(), out_q=self._out_q)
        self._current_runner = runner
        runner.start()

    def stop_running(self):
        if self._current_runner is not None and self._current_runner.is_alive():
            self._current_runner.stop()
            self._append_text("\n⏹ Stop requested\n", "warning")

    def _update_elapsed_time(self):
        """Update elapsed time display."""
        if self._start_time is not None:
            import time
            elapsed = time.time() - self._start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.elapsed_label.config(text=f"⏱ {minutes}m {seconds}s")

    def _poll(self):
        """Poll output queue and update GUI."""
        try:
            while True:
                tag, line = self._out_q.get_nowait()
                self._append_text(line, tag)
                
                if line.startswith("<process exited"):
                    self._set_job_buttons_enabled(True)
                    self.progress.stop()
                    
                    try:
                        code = int(line.strip().rstrip(">").rsplit(" ", 1)[-1])
                    except ValueError:
                        code = None
                    
                    if code == 0:
                        self._set_status("Ready — last run passed ✓", color="darkgreen", icon="✓")
                    elif code is None:
                        self._set_status("Ready", icon="✓")
                    else:
                        self._set_status(f"Ready — last run FAILED (exit {code})", color="red", icon="✗")
                    
                    self.refresh_store()
                    self._start_time = None
        except queue.Empty:
            pass
        
        self._update_elapsed_time()
        self.after(100, self._poll)

    # ===== ACTIONS =====

    def run_tests(self):
        """Run the production test suite."""
        self.text.configure(state=tk.NORMAL)
        self.text.delete(1.0, tk.END)
        self.text.configure(state=tk.DISABLED)
        self._append_text("\n" + "=" * 80 + "\n", "command")
        self._append_text("Running production test suite: run_all.py\n", "command")
        self._append_text("This runs 76 tests covering PIT correctness, costs, and risk gates.\n", "info")
        self._append_text("=" * 80 + "\n\n", "command")
        self._start_runner(["run_all.py"], label="run_all.py", cwd=MP_V01_DIR)

    def fetch_data(self):
        """Fetch market data."""
        tickers = self.tickers_var.get().strip()
        if not tickers:
            messagebox.showwarning("Fetch Data", "Enter at least one ticker (e.g. SPY,QQQ,MSFT) first.")
            return
        
        self.text.configure(state=tk.NORMAL)
        self.text.delete(1.0, tk.END)
        self.text.configure(state=tk.DISABLED)
        
        args = ["fetch_data.py", "--start", self.start_var.get(), "--end", self.end_var.get(), "--tickers", tickers]
        if self.chains_var.get():
            args.append("--chains")
        
        self._append_text("\n" + "=" * 80 + "\n", "command")
        self._append_text(f"Fetching market data: {' '.join(args)}\n", "command")
        self._append_text("=" * 80 + "\n\n", "command")
        self._start_runner(args, label="fetch_data.py", cwd=MP_V01_DIR)

    def run_mie(self):
        """Run Market Intelligence Engine (development only)."""
        tickers = self.mie_tickers_var.get().strip()
        if not tickers:
            messagebox.showwarning("Run MIE", "Enter at least one ticker (e.g. AAPL,MSFT,GOOGL) first.")
            return
        
        self.text.configure(state=tk.NORMAL)
        self.text.delete(1.0, tk.END)
        self.text.configure(state=tk.DISABLED)
        
        self._append_text("\n" + "=" * 80 + "\n", "warning")
        self._append_text("⚠️  MARKET INTELLIGENCE ENGINE - DEVELOPMENT ONLY\n", "warning")
        self._append_text("See CODE_REVIEW_2026-08-13.md for limitations and blockers.\n", "warning")
        self._append_text("=" * 80 + "\n\n", "warning")
        
        # Create a wrapper script to run MIE with custom tickers
        script_content = f"""
import sys
sys.path.insert(0, '{HERE}')

from market_intelligence_engine import MarketIntelligenceApp

tickers = '{tickers}'.split(',')
tickers = [t.strip() for t in tickers]

app = MarketIntelligenceApp()
results = app.run_analysis(tickers, {{'Technology': 'XLK', 'Healthcare': 'XLV'}})
app.generate_report('market_intelligence_report.json')
app.print_summary()
"""
        
        script_path = HERE / "_run_mie_temp.py"
        script_path.write_text(script_content)
        
        self._start_runner(["_run_mie_temp.py"], label="market_intelligence_engine.py", cwd=HERE)

    def refresh_store(self):
        """Refresh the data store browser."""
        self.store_list.delete(0, tk.END)
        if not DATA_DIR.exists():
            self.store_list.insert(tk.END, "(no data_store directory yet)")
            return
        
        for sub in ("bars", "chains"):
            d = DATA_DIR / sub
            if d.exists() and d.is_dir():
                files = list(d.iterdir())
                self.store_list.insert(tk.END, f"📁 {sub}/ ({len(files)} files)")
                for p in sorted(files)[:20]:  # Limit to first 20
                    self.store_list.insert(tk.END, f"  {p.name}")
                if len(files) > 20:
                    self.store_list.insert(tk.END, f"  ... and {len(files) - 20} more")

    def open_selected_file(self):
        """Open selected file from data store."""
        sel = self.store_list.curselection()
        if not sel:
            messagebox.showinfo("Open", "Select a file from the list first")
            return
        
        label = self.store_list.get(sel[0]).strip()
        if label.startswith("📁"):
            messagebox.showinfo("Open", "Select a file, not a directory")
            return
        if label.startswith("..."):
            messagebox.showinfo("Open", "Too many files to display. Check directory manually.")
            return
        
        # Remove leading spaces and reconstruct path
        label = label.lstrip()
        parent = self.store_list.get(sel[0] - 1).replace("📁 ", "").split("/")[0]
        path = DATA_DIR / parent / label
        
        if not path.exists():
            messagebox.showerror("Open", f"File not found: {path}")
            return
        
        try:
            text = path.read_text(encoding="utf-8")
            try:
                obj = json.loads(text)
                pretty = json.dumps(obj, indent=2, default=str)
                self._append_text(f"\n\n{'=' * 80}\n", "command")
                self._append_text(f"File: {label}\n", "command")
                self._append_text(f"{'=' * 80}\n\n", "command")
                self._append_text(pretty + "\n", "normal")
            except Exception:
                self._append_text(f"\n\n{'=' * 80}\n", "command")
                self._append_text(f"File: {label} (raw)\n", "command")
                self._append_text(f"{'=' * 80}\n\n", "command")
                self._append_text(text[:5000] + "\n", "normal")
                if len(text) > 5000:
                    self._append_text("...(truncated)\n", "info")
        except Exception as e:
            messagebox.showerror("Open", f"Failed to read file: {e}")

    def reveal_in_file_manager(self):
        """Open file manager to selected location."""
        sel = self.store_list.curselection()
        if not sel:
            path = DATA_DIR
        else:
            label = self.store_list.get(sel[0])
            if "📁" in label:
                parent = label.replace("📁 ", "").split("/")[0]
                path = DATA_DIR / parent
            else:
                path = DATA_DIR
        
        if not path.exists():
            messagebox.showerror("Reveal", f"Path not found: {path}")
            return
        
        try:
            if sys.platform.startswith("darwin"):
                subprocess.run(["open", str(path)])
            elif sys.platform.startswith("win"):
                subprocess.run(["explorer", str(path)])
            else:
                subprocess.run(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("Reveal", f"Failed to open file manager: {e}")


def main():
    app = MoneyPrinterGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
