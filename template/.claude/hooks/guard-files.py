#!/usr/bin/env python3
"""PreToolUse hook for Edit, Write and NotebookEdit: keep agents out of files they must not change.

- secrets: .env files (except .env.example), anything under secrets/, private keys
- Copier answers files (.copier-answers.*.yml): "NEVER EDIT MANUALLY"; change answers with
  `copier update --data key=value` instead (https://copier.readthedocs.io/en/stable/updating/)

Output follows https://code.claude.com/docs/en/hooks.md (PreToolUse decision control).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import PurePath

RULES: list[tuple[str, str]] = [
    (r"(^|/)\.env(\.(?!example$)[^/]+)?$", "Secrets files are not edited by agents; the owner manages .env."),
    (r"(^|/)secrets/", "Files under secrets/ are not edited by agents."),
    (r"\.(pem|key|p12|pfx)$", "Private keys are not edited by agents."),
    (r"(^|/)\.copier-answers\.[\w-]+\.yml$",
     "Copier answers files are never edited by hand; run `copier update -a <file> --data key=value`."),
]


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    posix = PurePath(path).as_posix()
    for pattern, reason in RULES:
        if re.search(pattern, posix):
            json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                              "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}}, sys.stdout)
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
