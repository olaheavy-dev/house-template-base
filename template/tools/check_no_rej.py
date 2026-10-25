#!/usr/bin/env python3
"""Fail when a conflicted `copier update --conflict rej` left `.rej` files behind.

`.gitignore` ignores `*.rej`, so pre-commit never passes them to a filename-filtered hook; this
script searches the working tree itself. Run by pre-commit on every commit and by `make check`.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKIP = {".git", "node_modules", ".venv", "bin", "obj", ".next"}


def leftovers(root: Path) -> list[Path]:
    found = []
    for path in root.rglob("*.rej"):
        if not SKIP.intersection(path.relative_to(root).parts):
            found.append(path.relative_to(root))
    return sorted(found)


def main() -> int:
    found = leftovers(Path.cwd())
    if found:
        print("A copier update left rejected changes. Apply or discard each, then delete the .rej file:")
        for path in found:
            print(f"  {path}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
