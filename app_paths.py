"""One output location for the GUI and every command-line entry point.

Defaults to ~/MoneyPrinterData, outside the checkout. MONEYPRINTER_HOME takes
precedence over the GUI's saved output_root. Importing this module writes nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = Path.home() / ".moneyprinter_gui.json"
OUTPUT_ENV = "MONEYPRINTER_HOME"


def read_settings() -> dict:
    try:
        value = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data_store"

    @property
    def picks(self) -> Path:
        return self.root / "picks"

    @property
    def excel(self) -> Path:
        return self.root / "excel_out"

    @property
    def picks_excel(self) -> Path:
        return self.root / "picks_out"

    @property
    def backtests(self) -> Path:
        return self.root / "backtests"

    @property
    def dashboard(self) -> Path:
        return self.root / "dashboard.html"


def get_paths(root: str | Path | None = None) -> AppPaths:
    chosen = (root or os.environ.get(OUTPUT_ENV) or read_settings().get("output_root")
              or Path.home() / "MoneyPrinterData")
    path = Path(chosen).expanduser().resolve()
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise ValueError("Choose an output folder outside the MoneyPrinter code checkout.")
    return AppPaths(path)


def migrate_legacy(paths: AppPaths, *, repo: Path = REPO_ROOT,
                   settings: dict | None = None) -> dict:
    """Copy known old outputs byte-for-byte; keep originals and all conflicts.

    Repeated launches are safe. A same-name/different-content file is retained
    under a deterministic digest suffix, never overwritten. No source code,
    credentials, symlinks or arbitrary files are copied.
    """
    saved = read_settings() if settings is None else settings
    sources = [
        (repo / "claude/app/mp_v01/data_store", paths.data, "**/*.json"),
        (repo / "data_store", paths.data, "**/*.json"),
        (repo / "picks", paths.picks, "picks_*.json"),
        (repo / "backtests", paths.backtests, "backtest_*.json"),
        (repo / "excel_out", paths.excel, "*.xlsx"),
        (repo / "picks_out", paths.picks_excel, "*.xlsx"),
        (repo, paths.root, "dashboard.html"),
        (repo, paths.root, "market_intelligence_report.json"),
    ]
    for key, target in (("outdir", paths.excel), ("picks_outdir", paths.picks_excel)):
        if saved.get(key):
            sources.append((Path(saved[key]).expanduser(), target, "*.xlsx"))
    result = {"copied": 0, "conflicts": [], "errors": []}
    for source, target, pattern in sources:
        if source.resolve() == target.resolve() or not source.is_dir():
            continue
        for old in sorted(source.glob(pattern)):
            if (not old.is_file() or old.is_symlink()
                    or source.resolve() not in old.resolve().parents):
                continue
            try:
                content = old.read_bytes()
                dest = target / old.relative_to(source)
                if dest.exists():
                    if dest.read_bytes() == content:
                        continue
                    suffix = hashlib.sha256(content).hexdigest()[:16]
                    dest = dest.with_name(f"{dest.stem}_legacy_{suffix}{dest.suffix}")
                    if dest.exists() and dest.read_bytes() == content:
                        continue
                    result["conflicts"].append(str(dest))
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive creation also protects against concurrent launches.
                with dest.open("xb") as output:
                    output.write(content)
                shutil.copystat(old, dest)
                result["copied"] += 1
            except OSError as exc:
                result["errors"].append(f"{old}: {exc}")
    return result
