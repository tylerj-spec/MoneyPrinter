#!/usr/bin/env python3
"""
Simple Tkinter GUI for MoneyPrinter (claude/app/mp_v01).

Features:
- Run the test suite (run_all.py) and show live output
- Run fetch_data.py with configurable tickers/start/end and optional --chains
- Browse the data_store/bars and data_store/chains directories and view JSON files

This GUI is intentionally dependency-free (stdlib only) so it can run with the
project's zero-dependency core. Run from the repository:

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
from tkinter import ttk, filedialog, messagebox

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data_store"


class SubprocessRunner(threading.Thread):
    def __init__(self, cmd, cwd: Path | None = None, env: dict | None = None, out_q: queue.Queue | None = None):
        super().__init__(daemon=True)
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.out_q = out_q or queue.Queue()
        self.proc = None

    def run(self):
        try:
            # Use the same Python interpreter as the GUI
            full_cmd = [sys.executable] + list(self.cmd)
            self.out_q.put(f"$ {' '.join(full_cmd)}\n")
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
                self.out_q.put(line)
            self.proc.wait()
            self.out_q.put(f"\n<process exited {self.proc.returncode}>\n")
        except Exception:
            self.out_q.put(traceback.format_exc())


class MoneyPrinterGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MoneyPrinter GUI")
        self.geometry("1000x700")

        # Top frame: controls
        ctrl = ttk.Frame(self)
        ctrl.pack(side=tk.TOP, fill=tk.X, padx=8, pady=6)

        # Run tests
        self.run_tests_btn = ttk.Button(ctrl, text="Run Tests (run_all.py)", command=self.run_tests)
        self.run_tests_btn.grid(row=0, column=0, padx=4, pady=2)

        # Fetch data controls
        ttk.Label(ctrl, text="Tickers:").grid(row=0, column=1, sticky=tk.E)
        self.tickers_var = tk.StringVar(value="SPY,QQQ,MSFT")
        self.tickers_entry = ttk.Entry(ctrl, textvariable=self.tickers_var, width=20)
        self.tickers_entry.grid(row=0, column=2, padx=4)

        ttk.Label(ctrl, text="Start:").grid(row=0, column=3, sticky=tk.E)
        self.start_var = tk.StringVar(value="2019-01-01")
        self.start_entry = ttk.Entry(ctrl, textvariable=self.start_var, width=12)
        self.start_entry.grid(row=0, column=4, padx=4)

        ttk.Label(ctrl, text="End:").grid(row=0, column=5, sticky=tk.E)
        self.end_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.end_entry = ttk.Entry(ctrl, textvariable=self.end_var, width=12)
        self.end_entry.grid(row=0, column=6, padx=4)

        self.chains_var = tk.BooleanVar(value=False)
        self.chains_cb = ttk.Checkbutton(ctrl, text="--chains (snapshot option chains)", variable=self.chains_var)
        self.chains_cb.grid(row=0, column=7, padx=8)

        self.fetch_btn = ttk.Button(ctrl, text="Fetch Data", command=self.fetch_data)
        self.fetch_btn.grid(row=0, column=8, padx=4)

        # Middle frame: output text and file browser
        middle = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        middle.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Left: output console
        out_frame = ttk.Frame(middle)
        middle.add(out_frame, weight=3)

        ttk.Label(out_frame, text="Console Output:").pack(anchor=tk.W)
        self.text = tk.Text(out_frame, wrap=tk.NONE)
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.configure(state=tk.DISABLED)

        # Right: data store browser
        browse_frame = ttk.Frame(middle, width=300)
        middle.add(browse_frame, weight=1)

        ttk.Label(browse_frame, text="Data Store Browser:").pack(anchor=tk.W)
        self.store_list = tk.Listbox(browse_frame, height=20)
        self.store_list.pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(browse_frame)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Refresh", command=self.refresh_store).pack(side=tk.LEFT, padx=4, pady=4)
        ttk.Button(btns, text="Open", command=self.open_selected_file).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Reveal in File Manager", command=self.reveal_in_file_manager).pack(side=tk.LEFT, padx=4)

        # Status bar
        self.status = ttk.Label(self, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        # Queue and poller
        self._out_q = queue.Queue()
        self._poll()

        # initial refresh
        self.refresh_store()

    # ----------------- subprocess helpers -----------------
    def _append_text(self, s: str):
        self.text.configure(state=tk.NORMAL)
        self.text.insert(tk.END, s)
        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)

    def _start_runner(self, args, cwd=None):
        self.status.config(text="Running...")
        runner = SubprocessRunner(args, cwd=cwd or HERE, env=os.environ.copy(), out_q=self._out_q)
        runner.start()

    def _poll(self):
        try:
            while True:
                line = self._out_q.get_nowait()
                self._append_text(line)
                if line.startswith("<process exited"):
                    self.status.config(text="Ready")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ----------------- actions -----------------
    def run_tests(self):
        # run run_all.py; ensure we run the script from its directory
        script = "run_all.py"
        self._append_text(f"\n=== Running tests: {script} ===\n")
        self._start_runner([script], cwd=HERE)

    def fetch_data(self):
        args = ["fetch_data.py", "--start", self.start_var.get(), "--end", self.end_var.get(), "--tickers", self.tickers_var.get()]
        if self.chains_var.get():
            args.append("--chains")
        self._append_text(f"\n=== Fetching data: {' '.join(args)} ===\n")
        self._start_runner(args, cwd=HERE)

    def refresh_store(self):
        self.store_list.delete(0, tk.END)
        if not DATA_DIR.exists():
            self.store_list.insert(tk.END, "(no data_store directory)")
            return
        for sub in ("bars", "chains"):
            d = DATA_DIR / sub
            if d.exists() and d.is_dir():
                self.store_list.insert(tk.END, f"-- {sub}/ --")
                for p in sorted(d.iterdir()):
                    self.store_list.insert(tk.END, str(p.relative_to(DATA_DIR)))
            else:
                self.store_list.insert(tk.END, f"-- {sub}/ (empty) --")

    def open_selected_file(self):
        sel = self.store_list.curselection()
        if not sel:
            messagebox.showinfo("Open", "Select a file from the list first")
            return
        label = self.store_list.get(sel[0])
        if label.startswith("--"):
            messagebox.showinfo("Open", "Select a file entry, not a directory header")
            return
        path = DATA_DIR / label
        if not path.exists():
            messagebox.showerror("Open", f"File not found: {path}")
            return
        try:
            text = path.read_text(encoding="utf-8")
            try:
                obj = json.loads(text)
                pretty = json.dumps(obj, indent=2, default=str)
                self._append_text(f"\n=== {label} ===\n{pretty}\n=== end ===\n")
            except Exception:
                # not JSON or JSON parse error - just print head
                self._append_text(f"\n=== {label} (raw) ===\n{text[:2000]}\n...\n=== end ===\n")
        except Exception as e:
            messagebox.showerror("Open", f"Failed to read file: {e}")

    def reveal_in_file_manager(self):
        sel = self.store_list.curselection()
        if not sel:
            messagebox.showinfo("Reveal", "Select a file from the list first")
            return
        label = self.store_list.get(sel[0])
        if label.startswith("--"):
            path = DATA_DIR
        else:
            path = DATA_DIR / label
        if not path.exists():
            messagebox.showerror("Reveal", f"Path not found: {path}")
            return
        try:
            if sys.platform.startswith("darwin"):
                subprocess.run(["open", path])
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
