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

import json
import re
import sys
from pathlib import PurePath

WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}

# (pattern, applies to reads too, reason)
RULES: list[tuple[str, bool, str]] = [
    (r"(^|/)\.env(\.(?!example$)[^/]+)?$", True,
     "Secret env files are off limits to agents; use .env.example for names and ask the owner for values."),
    (r"(^|/)secrets/", True, "Files under secrets/ are off limits to agents."),
    (r"\.(pem|key|p12|pfx)$", True, "Private keys are off limits to agents."),
    (r"(^|/)\.copier-answers\.[\w-]+\.yml$", False,
     "Copier answers files are never edited by hand; run `copier update -a <file> --data key=value`."),
]


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool = event.get("tool_name") or ""
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or ""
    posix = PurePath(path).as_posix()
    writing = tool in WRITE_TOOLS
    for pattern, applies_to_reads, reason in RULES:
        if (writing or applies_to_reads) and re.search(pattern, posix):
            json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                              "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}}, sys.stdout)
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
