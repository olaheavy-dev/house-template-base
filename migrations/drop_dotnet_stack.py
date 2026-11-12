"""Before an update: take the retired `dotnet` stack out of the base answers file.

The `dotnet` choice was removed from the `stacks` question (owner decision, 12 Nov 2026). Copier
drops a saved answer that is no longer a valid choice and falls back to the question's default
(fastapi and nextjs), so without this step an update with --defaults would quietly switch a .NET
project to the FastAPI and Next.js toolchains. This keeps the project's other stacks instead.
It changes nothing when `dotnet` isn't there, so it is safe on every update.
Copier migrations: https://copier.readthedocs.io/en/stable/configuring/#migrations
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml  # Copier depends on PyYAML, and this runs with Copier's own Python.


def main(answers_file: str) -> int:
    path = Path(answers_file)
    if not path.is_file():
        return 0
    text = path.read_text()
    answers = yaml.safe_load(text) or {}
    stacks = answers.get("stacks")
    if not isinstance(stacks, list) or "dotnet" not in stacks:
        return 0
    answers["stacks"] = [stack for stack in stacks if stack != "dotnet"]
    header = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
    path.write_text(header + yaml.safe_dump(answers, default_flow_style=False, sort_keys=False))
    print(f"house-template-base no longer has a dotnet stack: {answers_file} now has stacks "
          f"{answers['stacks']}. The update stops generating the .NET parts of the base files "
          "(CodeQL csharp, NuGet and .NET SDK Dependabot, the CI .NET step); review them in the diff.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
