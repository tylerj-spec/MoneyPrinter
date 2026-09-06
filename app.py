#!/usr/bin/env python3
"""MoneyPrinter desktop entrypoint with local-first data and review controls."""
from __future__ import annotations
from pathlib import Path
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from gui import MoneyPrinterGUI, HERE
sys.path.insert(0, str(HERE / "claude/app/mp_v01/src"))
from localdata.providers import PROVIDERS
from ui_theme import apply_theme


class ResearchApp(MoneyPrinterGUI):
    def __init__(self):
        self.source_credentials = {}
        super().__init__()
        menu = self.nametowidget(self.cget("menu"))
        data = tk.Menu(menu, tearoff=False)
        for label, command in (
            ("Data sources and API keys", self.data_sources),
            ("Refresh free public context", self.refresh_public),
            ("Inspect local archive", self.archive_status),
            ("Import manual JSON context", self.import_context),
            ("Why this pick? Latest forward record", self.review_latest),
            ("Why this pick? Choose record", self.review_choose),
            ("Local paper-account status", self.paper_status),
            ("Create feedback ZIP (local only)", self.feedback)):
            data.add_command(label=label, command=command)
        menu.add_cascade(label="Data and review", menu=data)
        self._apply_theme()

    def refresh_public(self):
        self._banner("Refreshing free public context; no broker orders")
        self._start([HERE / "collect_data.py", "public"], "public context", HERE)

    def archive_status(self):
        self._start([HERE / "collect_data.py", "status"], "archive status", HERE)

    def data_sources(self):
        win = tk.Toplevel(self)
        win.title("Local data sources - credentials stay in memory")
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        provider = tk.StringVar(win, value="fred")
        scope = tk.StringVar(win, value="DGS10")
        production = tk.BooleanVar(win, value=False)
        vintage = tk.StringVar(win, value="")
        ttk.Label(frame, text="Provider").grid(row=0, column=0, sticky="w")
        select = ttk.Combobox(frame, values=tuple(PROVIDERS), textvariable=provider, state="readonly", width=35)
        select.grid(row=0, column=1, sticky="ew")
        select.bind("<<ComboboxSelected>>", lambda e: scope.set(PROVIDERS[provider.get()]["scope"]))
        ttk.Label(frame, text="Scope: series / CIK / symbol").grid(row=1, column=0, sticky="w")
        ttk.Entry(frame, textvariable=scope, width=38).grid(row=1, column=1, sticky="ew")
        ttk.Label(frame, text="FRED vintage (blank = today)").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=vintage).grid(row=2, column=1, sticky="ew")
        names = tuple(dict.fromkeys(k for cfg in PROVIDERS.values() for k in cfg["credentials"]))
        for row, name in enumerate(names, 3):
            variable = self.source_credentials.setdefault(name, tk.StringVar(self, value=os.environ.get(name, "")))
            ttk.Label(frame, text=name).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(frame, textvariable=variable, show="*", width=38).grid(row=row, column=1, sticky="ew")
        row = len(names) + 3
        ttk.Checkbutton(frame, text="Tradier production market data (requires brokerage access)", variable=production).grid(row=row, columnspan=2, sticky="w", pady=8)
        ttk.Label(frame, text="SEC_USER_AGENT is your name + contact email, not a key.\nMassive remains in the main key box. No paid upgrade occurs here.\nAlpaca is forced to the free indicative feed; not executable quotes.\nNew archives add context; they do not automatically change predictions.", wraplength=610).grid(row=row+1, columnspan=2, sticky="w", pady=8)
        def fetch():
            chosen = provider.get()
            env = {k: self.source_credentials[k].get().strip() for k in PROVIDERS[chosen]["credentials"]}
            if any(not value for value in env.values()):
                messagebox.showwarning("Missing credential", "Fill the fields required for this provider.", parent=win)
                return
            args = [HERE / "collect_data.py", chosen, "--scope", scope.get().strip()]
            if vintage.get().strip():
                args += ["--vintage", vintage.get().strip()]
            if production.get() and chosen == "tradier":
                args.append("--production")
            self._start(args, "collect " + chosen, HERE, env_extra=env)
        ttk.Button(frame, text="Fetch and archive locally", command=fetch).grid(row=row+2, column=1, sticky="e")
        ttk.Button(frame, text="Close", command=win.destroy).grid(row=row+2, column=0, sticky="w")
        frame.columnconfigure(1, weight=1)
        apply_theme(self, self.theme_var.get())

    def import_context(self):
        path = filedialog.askopenfilename(title="Import moneyprinter.manual.v1 JSON", filetypes=[("JSON", "*.json")])
        if path:
            self._start([HERE / "collect_data.py", "import", "--file", path], "manual context import", HERE)

    def _review(self, path):
        target = self.paths.root / "reviews" / (Path(path).stem + ".html")
        if self._start([HERE / "pick_review.py", "--file", path, "--out", target], "pick explanation", HERE):
            self._pending_dashboard = target

    def review_latest(self):
        path = self._newest_pick_file()
        if path:
            self._review(path)
        else:
            messagebox.showinfo("No picks", "Generate a forward pick or choose a historical replay record.")

    def review_choose(self):
        path = filedialog.askopenfilename(title="Choose a frozen forward or historical pick record", filetypes=[("JSON", "*.json")])
        if path:
            self._review(path)

    def paper_status(self):
        self._start([HERE / "paper_trading.py", "status"], "paper status", HERE)

    def feedback(self):
        self._start([HERE / "feedback_bundle.py"], "local feedback ZIP", HERE)

    def _on_close(self):
        for variable in self.source_credentials.values():
            variable.set("")
        super()._on_close()


if __name__ == "__main__":
    ResearchApp().mainloop()
