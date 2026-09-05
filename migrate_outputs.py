#!/usr/bin/env python3
"""Copy old runtime files outside the checkout, preserving the originals."""
import argparse
import sys
from pathlib import Path

from app_paths import REPO_ROOT, get_paths, migrate_legacy


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-code-dir", type=Path, default=REPO_ROOT)
    ap.add_argument("--output-root", type=Path)
    args = ap.parse_args(argv)
    paths = get_paths(args.output_root)
    result = migrate_legacy(paths, repo=args.from_code_dir.resolve())
    print(f"Output folder: {paths.root}")
    print(f"Copied {result['copied']} file(s). Originals preserved.")
    for dest in result["conflicts"]:
        print(f"Preserved same-name conflict: {dest}")
    for error in result["errors"]:
        print(f"ERROR: {error}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
