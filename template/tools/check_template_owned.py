#!/usr/bin/env python3
"""Flag changes to files a template layer owns, so generic improvements go upstream.

Each layer lists the files it owns in .github/template-owned/<layer>.txt (one glob per line). When
a pull request changes one, CI prints a warning annotation: improve the template layer first and
let the weekly template update bring the change back, or label the PR `template-candidate` so it
gets carried upstream. It never fails the build: some changes are legitimately local.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path


def owned_patterns(root: Path) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for listing in sorted((root / ".github" / "template-owned").glob("*.txt")):
        lines = [ln.strip() for ln in listing.read_text().splitlines()]
        owners[listing.stem] = [ln for ln in lines if ln and not ln.startswith("#")]
    return owners


def changed_files(base: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], capture_output=True,
                         text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def owner_of(path: str, owners: dict[str, list[str]]) -> str | None:
    for layer, patterns in owners.items():
        if any(fnmatch.fnmatch(path, pattern) for pattern in patterns):
            return layer
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="git ref to compare with, e.g. origin/main")
    args = parser.parse_args(argv)
    owners = owned_patterns(Path.cwd())
    flagged = [(path, layer) for path in changed_files(args.base)
               if (layer := owner_of(path, owners))]
    for path, layer in flagged:
        print(f"::warning file={path}::Owned by house-template-{layer}. If this improvement is generic, "
              f"make it in the template layer (or label the PR template-candidate) so every project gets it.")
    if not flagged:
        print("No template-owned files changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
