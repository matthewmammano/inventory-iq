"""Flag em-dashes and " -- " used as prose punctuation in source/docs.

A bare "--" with no surrounding spaces is a CSS custom property (--font-scale)
or a CLI flag (--devices) and is never flagged. Only a space-dash-dash-space
run, or a literal em-dash character, counts as a hit.

Usage:
    .venv/bin/python3 -m scripts.check_dashes [path ...]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

EM_DASH = "—"
DOUBLE_HYPHEN_PATTERN = re.compile(r"\s--\s")
SCANNED_SUFFIXES = {".py", ".css", ".js", ".md", ".html"}
EXCLUDED_DIR_NAMES = {".git", ".venv", "node_modules", "__pycache__", "instance"}
EXCLUDED_PATH_PARTS = ("scripts/device_screenshots/output",)


@dataclass(frozen=True, slots=True)
class DashHit:
    path: Path
    line_number: int
    line_text: str


def is_scannable(path: Path) -> bool:
    if path.suffix not in SCANNED_SUFFIXES:
        return False
    if EXCLUDED_DIR_NAMES & set(path.parts):
        return False
    posix = path.as_posix()
    return not any(excluded in posix for excluded in EXCLUDED_PATH_PARTS)


def find_hits(path: Path) -> list[DashHit]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    hits = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if EM_DASH in line or DOUBLE_HYPHEN_PATTERN.search(line):
            hits.append(DashHit(path, line_number, line.strip()))
    return hits


def scan(root: Path) -> list[DashHit]:
    hits = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and is_scannable(path):
            hits.extend(find_hits(path))
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["."], help="Files or directories to scan")
    args = parser.parse_args()

    all_hits = []
    for raw_path in args.paths:
        path = Path(raw_path)
        all_hits.extend(find_hits(path) if path.is_file() else scan(path))

    if not all_hits:
        print('No em-dashes or prose "--" found.')
        return

    for hit in all_hits:
        print(f"{hit.path}:{hit.line_number}: {hit.line_text}")
    print(f"\n{len(all_hits)} hit(s).")
    sys.exit(1)


if __name__ == "__main__":
    main()
