#!/usr/bin/env python3
"""PreToolUse hook for the file tools: keep agents out of secrets, and out of files they must not change.

- secrets, in any folder (read or write): every .env file except .env.example, anything under
  secrets/, private keys. A permission deny rule can't make the .env.example exception, so this
  hook is the main control and `.claude/settings.json` denies the common names as a second layer.
- Copier answers files (.copier-answers.*.yml), write only: "NEVER EDIT MANUALLY"; change answers
  with `copier update --data key=value` (https://copier.readthedocs.io/en/stable/updating/)

Output follows https://code.claude.com/docs/en/hooks.md (PreToolUse decision control).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
import time
from pathlib import Path, PurePath

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
# An explicit Grep glob makes ripgrep search ignored and hidden files too, so the hook lists the
# files the glob would reach and refuses if any is a secret. Dependency and VCS folders are skipped;
# a listing that runs too long fails closed.
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".next", "bin", "obj"}
MAX_FILES, MAX_SECONDS = 200_000, 3.0

# (pattern, applies to reads too, reason)
RULES: list[tuple[str, bool, str]] = [
    (r"(^|/)\.env(\.(?!example$)[^/]+)?$", True,
     "Secret env files are off limits to agents; use .env.example for names and ask the owner for values."),
    (r"(^|/)secrets/", True, "Files under secrets/ are off limits to agents."),
    (r"\.(pem|key|p12|pfx)$", True, "Private keys are off limits to agents."),
    (r"(^|/)\.copier-answers\.[\w-]+\.yml$", False,
     "Copier answers files are never edited by hand; run `copier update -a <file> --data key=value`."),
]


def expand_braces(glob: str) -> list[str]:
    """`{a,b}` alternatives as ripgrep reads them (fnmatch has no braces). Nested braces expand too."""
    match = re.search(r"\{([^{}]*)\}", glob)
    if not match:
        return [glob]
    head, tail = glob[:match.start()], glob[match.end():]
    return [out for option in match.group(1).split(",") for out in expand_braces(head + option + tail)]


def is_secret(rel: str) -> bool:
    return any(applies and re.search(pattern, "/" + rel) for pattern, applies, _ in RULES)


def grep_reaches_secret(base: Path, glob: str) -> bool:
    """True when a file under `base` that `glob` selects is a secret, or the listing can't finish.
    fnmatch's `*` also crosses `/`, so it can over-match ripgrep: that errs towards refusing."""
    options = expand_braces(glob.lower())
    def selected(rel: str) -> bool:
        name = rel.rsplit("/", 1)[-1]
        return any(fnmatch.fnmatch(rel, o) or fnmatch.fnmatch(name, o) for o in options)
    if base.is_file():
        rel = base.name.lower()
        return selected(rel) and is_secret(rel)
    started, seen = time.monotonic(), 0
    for folder, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for file in files:
            seen += 1
            if seen > MAX_FILES or time.monotonic() - started > MAX_SECONDS:
                return True  # fail closed
            rel = os.path.relpath(os.path.join(folder, file), base).replace(os.sep, "/").lower()
            if selected(rel) and is_secret(rel):
                return True
    return False


def deny(reason: str) -> None:
    json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": reason}}, sys.stdout)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool = event.get("tool_name") or ""
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or ""
    # Case-insensitive: macOS and Windows filesystems open .ENV as .env.
    posix = PurePath(path).as_posix().lower()
    writing = tool in WRITE_TOOLS
    glob = str(tool_input.get("glob") or "")
    if tool == "Grep" and glob:
        base = Path(path) if path else Path(event.get("cwd") or ".")
        if grep_reaches_secret(base, glob):
            deny(f"The glob `{glob}` reaches secret files (.env, secrets/, keys), which an explicit glob "
                 "searches even when git ignores them. Use a narrower glob.")
            return 0
    for pattern, applies_to_reads, reason in RULES:
        if (writing or applies_to_reads) and re.search(pattern, posix):
            deny(reason)
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
