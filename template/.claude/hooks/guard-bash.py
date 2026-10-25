#!/usr/bin/env python3
"""PreToolUse hook for Bash: enforce the repository's guardrails on the whole command line.

Permission rules match commands as written, so `git -C . push` or `sh -c 'git push'` slip past a
`Bash(git push *)` rule (https://code.claude.com/docs/en/permissions.md). This hook reads the full
command and denies what must never happen, or asks for what needs a person:

- deny: pushing to main (by refspec, a bare push from main, or a bulk push such as --all),
  force pushes, skipping git hooks, reading .env files from the shell, and commit messages that
  credit a coding agent (AGENTS.md rule 5)
- ask: commands that discard local work (git reset --hard, git clean, git checkout -- .)

Input and output follow https://code.claude.com/docs/en/hooks.md (PreToolUse decision control).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

PROTECTED = ("main", "master")
BULK_PUSH = {"--all", "--branches", "--mirror", "--prune"}

DENY: list[tuple[str, str]] = [
    (r"\bgit\b[^;&|]*\bpush\b[^;&|]*(\s--force\b|\s-f\b|\s--force-with-lease\b|\s\+\S)",
     "Force pushes are not allowed. Push a new commit instead."),
    (r"\bgit\b[^;&|]*\b(commit|push|merge|rebase)\b[^;&|]*\s--no-verify\b",
     "Skipping git hooks (--no-verify) is not allowed. Fix what the hook reports."),
    (r"(?i)co-authored-by:\s*[^\n]*(claude|anthropic|codex|openai|copilot|cursor|gemini|agent)",
     "Commit messages carry no coding-agent attribution (AGENTS.md rule 5)."),
    (r"(?i)generated with \[?claude",
     "Commit messages and PR text carry no coding-agent attribution (AGENTS.md rule 5)."),
    (r"(^|[\s'\"=/<])\.env(\.(?!example\b)[\w.-]+)?(?=$|[\s'\";|&)>])",
     "Reading .env files is not allowed; use .env.example for names and ask the owner for values."),
]

ASK: list[tuple[str, str]] = [
    (r"\bgit\b[^;&|]*\breset\b[^;&|]*--hard\b", "git reset --hard discards local work."),
    (r"\bgit\b[^;&|]*\bclean\b[^;&|]*\s-[a-zA-Z]*f", "git clean deletes untracked files."),
    (r"\bgit\b[^;&|]*\bcheckout\b[^;&|]*\s--\s+\.", "git checkout -- . discards local changes."),
    (r"\bgit\b[^;&|]*\brestore\b[^;&|]*\s\.(\s|$)", "git restore . discards local changes."),
]


def current_branch() -> str:
    # symbolic-ref also names the branch before its first commit, where rev-parse prints "HEAD".
    try:
        out = subprocess.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=5, check=False)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def pushes_to_protected(command: str) -> bool:
    """True when a `git push` in the command targets a protected branch: named in a refspec's
    destination, or, when no refspec is given, because the current branch is protected."""
    for part in re.split(r"&&|\|\||;|\||\n", command):
        match = re.search(r"\bgit\b.*?\bpush\b(.*)", part)
        if not match:
            continue
        words = match.group(1).split()
        if BULK_PUSH.intersection(w.split("=")[0] for w in words):
            return True  # --all, --mirror and --prune update every branch, main included
        args = [a.strip("'\"") for a in words if not a.startswith("-")]
        refspecs = args[1:]  # args[0] is the remote
        if not refspecs:
            if current_branch() in PROTECTED:
                return True
            continue
        for spec in refspecs:
            destination = spec.split(":")[-1].removeprefix("refs/heads/")
            if destination in PROTECTED or (destination == "HEAD" and current_branch() in PROTECTED):
                return True
    return False


def decide(command: str) -> tuple[str, str] | None:
    if pushes_to_protected(command):
        return "deny", "Pushing to main is not allowed. Push a branch and open a pull request."
    for pattern, reason in DENY:
        if re.search(pattern, command):
            return "deny", reason
    for pattern, reason in ASK:
        if re.search(pattern, command):
            return "ask", reason
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    verdict = decide(command)
    if verdict:
        decision, reason = verdict
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "permissionDecision": decision,
                                          "permissionDecisionReason": reason}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
