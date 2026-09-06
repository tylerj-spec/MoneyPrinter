"""Application-owned light/dark colors. No packages or network required.

Native window borders and OS file/message dialogs retain the operating system's
appearance. Theme changes never rewrite market data, picks or API credentials.
"""
from __future__ import annotations

_PALETTES = {
    "light": {
        "background": "#F3F5F7", "surface": "#FFFFFF", "control": "#E5EAF0",
        "normal": "#15202B", "muted": "#506070", "border": "#BAC4CE",
        "selection": "#2458A6", "selected_text": "#FFFFFF",
        "success": "#176533", "error": "#AE2525", "warning": "#875400",
        "command": "#2458A6", "info": "#506070",
    },
    "dark": {
        "background": "#161B22", "surface": "#202833", "control": "#303C4C",
        "normal": "#EEF2F6", "muted": "#B4C0CF", "border": "#526176",
        "selection": "#366BAC", "selected_text": "#FFFFFF",
        "success": "#84DCA0", "error": "#FFA49B", "warning": "#F4CC79",
        "command": "#9BC8FF", "info": "#B4C0CF",
    },
}


def normalise_theme(value: object) -> str:
    return value if isinstance(value, str) and value in _PALETTES else "light"


def palette_for(value: object) -> dict[str, str]:
    # Do not let callers change the global palette.
    return dict(_PALETTES[normalise_theme(value)])


def log_styles(value: object) -> dict[str, dict[str, str]]:
    colors = palette_for(value)
    return {role: {"foreground": colors[role]}
            for role in ("normal", "success", "error", "warning", "command", "info")}


def apply_theme(root, value: object) -> None:
    """Style existing widgets, including open help windows, without rebuilding UI."""
    import tkinter as tk
    from tkinter import ttk

    p = palette_for(value)
    style = ttk.Style(root)
    # Native Windows themes can ignore explicit background settings. Clam is
    # supplied with Tk and makes both themes consistent across platforms.
    if style.theme_use() != "clam":
        style.theme_use("clam")
    style.configure(".", background=p["background"], foreground=p["normal"],
                    bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"])
    for name in ("TFrame", "TLabel", "TLabelframe", "TLabelframe.Label"):
        style.configure(name, background=p["background"], foreground=p["normal"])
    style.configure("Muted.TLabel", foreground=p["muted"])
    style.configure("TButton", background=p["control"], foreground=p["normal"], padding=5)
    style.map("TButton", background=[("active", p["selection"]), ("disabled", p["background"])],
              foreground=[("disabled", p["muted"]), ("active", p["selected_text"])])
    for name in ("TEntry", "TCombobox"):
        style.configure(name, fieldbackground=p["surface"], foreground=p["normal"],
                        insertcolor=p["normal"], selectbackground=p["selection"],
                        selectforeground=p["selected_text"], arrowcolor=p["normal"])
        style.map(name, fieldbackground=[("readonly", p["surface"]), ("disabled", p["control"])],
                  foreground=[("disabled", p["muted"]), ("readonly", p["normal"])])
    style.configure("Horizontal.TProgressbar", background=p["selection"],
                    troughcolor=p["control"])
    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(name, background=p["control"], troughcolor=p["background"],
                        arrowcolor=p["normal"])
    # The combobox popup is a classic Tk listbox created on demand.
    root.option_add("*TCombobox*Listbox.background", p["surface"])
    root.option_add("*TCombobox*Listbox.foreground", p["normal"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["selection"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["selected_text"])

    def visit(widget) -> None:
        if isinstance(widget, (tk.Tk, tk.Toplevel, tk.Frame)):
            widget.configure(background=p["background"])
        elif isinstance(widget, tk.Text):
            widget.configure(background=p["surface"], foreground=p["normal"],
                             insertbackground=p["normal"], selectbackground=p["selection"],
                             selectforeground=p["selected_text"])
            for tag, options in log_styles(value).items():
                widget.tag_configure(tag, **options)
            if "note" in widget.tag_names():
                widget.tag_configure("note", foreground=p["warning"])
        elif isinstance(widget, tk.Menu):
            widget.configure(background=p["surface"], foreground=p["normal"],
                             activebackground=p["selection"], activeforeground=p["selected_text"],
                             disabledforeground=p["muted"])
        elif isinstance(widget, tk.Scrollbar):
            widget.configure(background=p["control"], troughcolor=p["background"],
                             activebackground=p["selection"])
        for child in widget.winfo_children():
            visit(child)

    visit(root)
