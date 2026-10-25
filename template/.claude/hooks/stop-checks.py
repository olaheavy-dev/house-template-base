#!/usr/bin/env python3
"""Stop hook: before the agent finishes a turn that changed files, run `make check-fast`.

If the checks fail, the hook blocks the stop and hands the failure back, so the agent fixes it
instead of reporting success. It does nothing when nothing changed (no uncommitted files and no
unpushed commits), and it never blocks twice in a row (`stop_hook_active`), so a check that can't
pass can't trap the session.
Claude Code also caps consecutive stop-hook continuations at 8.

Input and output follow https://code.claude.com/docs/en/hooks.md (Stop input, Stop decision control).
"""

from __future__ import annotations

import json
import subprocess
import sys

TAIL_LINES = 60


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=15, check=False).stdout.strip()


def unpushed_commits() -> bool:
    """Commits on this branch that no remote has yet. Not compared with @{upstream}: a branch
    started from origin/main tracks it, so pushed commits would still look "ahead". In a
    repository with no remote at all, none count (before the first push every commit would)."""
    if git("for-each-ref", "--count=1", "refs/remotes"):
        return bool(git("log", "HEAD", "--not", "--remotes", "--oneline", "-1"))
    return False


def has_changes() -> bool:
    """Uncommitted changes, or commits an agent may have made during the turn. Pushed commits
    already passed `make check-fast` in the pre-push hook."""
    return bool(git("status", "--porcelain")) or unpushed_commits()


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if event.get("stop_hook_active") or not has_changes():
        return 0
    run = subprocess.run(["make", "check-fast"], capture_output=True, text=True, timeout=570,
                         check=False)
    if run.returncode == 0:
        return 0
    tail = "\n".join((run.stdout + run.stderr).strip().splitlines()[-TAIL_LINES:])
    json.dump({"decision": "block",
               "reason": f"`make check-fast` failed on the current changes. Fix it before finishing:\n{tail}"},
              sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
