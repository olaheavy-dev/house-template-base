#!/usr/bin/env python3
"""PreToolUse hook for Bash: enforce the repository's guardrails on the whole command line.

Permission rules match commands as written, so `git -C . push` or `sh -c 'git push'` slip past a
`Bash(git push *)` rule (https://code.claude.com/docs/en/permissions.md). This hook parses the
command instead: it splits it at shell operators, tokenises each part with shell quoting rules,
follows `sh -c` / `bash -c` into their scripts, and reads git's global options (`-C`,
`--git-dir`, `--work-tree`) before judging a `git push`. What it can't parse, it fails closed on.

- pushes: an allow-list. Agents push only as `git push [-u] <remote> <branch>` (or a bare push
  from a known feature branch); anything else is refused: main, force, --all, --mirror,
  matching or wildcard refspecs, tags as destinations, unknown flags
- deny: skipping git hooks, reading .env files from the shell, and commit
  messages or PR text that credit a coding agent (AGENTS.md rule 5)
- ask: commands that discard local work (git reset --hard, git clean, git checkout -- .)

This is the local, early guard. The server-side boundary is the ruleset on GitHub, which rejects
force pushes and direct pushes to main whatever runs locally.

Input and output follow https://code.claude.com/docs/en/hooks.md (PreToolUse decision control).
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field

PROTECTED = {"main", "master"}
SHELLS = {"sh", "bash", "zsh", "dash"}
SAFE_PUSH_FLAGS = {"-u", "--set-upstream", "-n", "--dry-run", "-v", "--verbose", "-q", "--quiet", "--tags", "--follow-tags", "--no-progress", "--progress"}
REMOTE_NAME = re.compile(r"[A-Za-z0-9][\w.-]*")
# A plain branch: no wildcard, no HEAD, no ref outside refs/heads/, no leading dash or dot.
BRANCH_NAME = re.compile(r"(refs/heads/)?(?!refs/)[A-Za-z0-9](?:[\w/-]|\.(?!\.))*(?<![./])")
FORCE_LONG = ("--force", "--force-with-lease", "--force-if-includes")
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
CONTEXT_CHANGERS = re.compile(r"\bgit\b.*\b(switch|checkout|worktree)\b|(^|\s)(cd|pushd|popd)(\s|$)")

DENY_TEXT: list[tuple[str, str]] = [
    (r"(?i)co-authored-by:\s*[^\n]*(claude|anthropic|codex|openai|copilot|cursor|gemini|agent)",
     "Commit messages carry no coding-agent attribution (AGENTS.md rule 5)."),
    (r"(?i)generated with \[?claude",
     "Commit messages and PR text carry no coding-agent attribution (AGENTS.md rule 5)."),
    (r"(^|[\s'\"=/<])\.env(\.(?!example\b)[\w.-]+)?(?=$|[\s'\";|&)>])",
     "Reading .env files is not allowed; use .env.example for names and ask the owner for values."),
]

ASK_TEXT: list[tuple[str, str]] = [
    (r"\bgit\b[^;&|]*\breset\b[^;&|]*--hard\b", "git reset --hard discards local work."),
    (r"\bgit\b[^;&|]*\bclean\b[^;&|]*\s-[a-zA-Z]*f", "git clean deletes untracked files."),
    (r"\bgit\b[^;&|]*\bcheckout\b[^;&|]*\s--\s+\.", "git checkout -- . discards local changes."),
    (r"\bgit\b[^;&|]*\brestore\b[^;&|]*\s\.(\s|$)", "git restore . discards local changes."),
]

MAIN = "Pushing to main is not allowed. Push a named branch (git push origin <branch>) and open a pull request."
FORCE = "Force pushes are not allowed. Push a new commit instead."
NO_VERIFY = "Skipping git hooks (--no-verify) is not allowed. Fix what the hook reports."
UNPARSEABLE = "This command line can't be parsed safely, so the push is refused. Run the push on its own."
NAME_THE_BRANCH = ("Name the branch: `git push [-u] origin <branch>`. A bare push follows push.default and "
                   "remote.<name>.push, which can point at main.")
UNUSUAL_PUSH = ("Agents push only as `git push [-u] <remote> <branch>`; `{}` is outside that. "
                "Ask the owner if this push is needed.")


@dataclass
class Git:
    """One git invocation: where it runs and what it does."""

    cwd: str | None = None
    unknown_repo: bool = False  # --git-dir or --work-tree: the branch can't be read reliably
    subcommand: str = ""
    args: list[str] = field(default_factory=list)


def branch_of(cwd: str | None) -> str:
    # symbolic-ref also names the branch before its first commit, where rev-parse prints "HEAD".
    cmd = ["git"] + (["-C", cwd] if cwd else []) + ["symbolic-ref", "--quiet", "--short", "HEAD"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_git(tokens: list[str]) -> Git | None:
    """Read git's global options up to the subcommand. None if this isn't a git invocation."""
    if not tokens or tokens[0].rsplit("/", 1)[-1] != "git":
        return None
    git, i = Git(), 1
    while i < len(tokens) and tokens[i].startswith("-"):
        opt, _, inline = tokens[i].partition("=")
        value = inline or (tokens[i + 1] if opt in GIT_VALUE_OPTIONS and not inline and i + 1 < len(tokens) else "")
        if opt == "-C":
            git.cwd = value if git.cwd is None or value.startswith("/") else f"{git.cwd}/{value}"
        elif opt in {"--git-dir", "--work-tree"}:
            git.unknown_repo = True
        i += 2 if opt in GIT_VALUE_OPTIONS and not inline else 1
    if i < len(tokens):
        git.subcommand, git.args = tokens[i], tokens[i + 1:]
    return git


def judge_push(git: Git, context_changed: bool) -> str | None:
    """Allow-list: agents push only in the plain forms they need, everything else is refused.

    Allowed: optional flags from SAFE_PUSH_FLAGS, then an optional remote, then branch names or
    `branch:branch` pairs, none of them protected; or a bare push from a known, unprotected branch.
    Refused: any other flag (force, --all, --mirror, --delete, -o, ...), "+" refspecs, ":" and
    wildcards, tags or other refs as destinations, and a push of HEAD or a bare push whose
    current branch is unknown or protected.
    """
    positional = []
    for arg in git.args:
        if arg.startswith("-"):
            opt = arg.split("=", 1)[0]
            if opt == "--no-verify":
                return NO_VERIFY
            if opt.startswith(FORCE_LONG) or (re.fullmatch(r"-[a-zA-Z]+", arg) and "f" in arg[1:]):
                return FORCE
            if opt not in SAFE_PUSH_FLAGS:
                return UNUSUAL_PUSH.format(arg)
            continue
        positional.append(arg)
    if positional and not REMOTE_NAME.fullmatch(positional[0]):
        return UNUSUAL_PUSH.format(positional[0])
    refspecs = positional[1:]  # positional[0] is the remote
    if not refspecs and "--tags" in git.args:
        return None  # pushes tags only, never branches
    if not refspecs:
        # A bare push goes wherever push.default and remote.<name>.push send it (HEAD:main is a
        # valid setting), so agents always name the branch; an explicit refspec overrides both.
        return NAME_THE_BRANCH
    for spec in refspecs:
        if spec.startswith("+"):
            return FORCE
        names = spec.split(":")
        if len(names) > 2 or not all(BRANCH_NAME.fullmatch(n) for n in names):
            return UNUSUAL_PUSH.format(spec)
        destination = names[-1].removeprefix("refs/heads/")
        if destination in PROTECTED:
            return MAIN
        if destination == "HEAD":  # the current branch: only when it is known and unprotected
            if context_changed or git.unknown_repo:
                return MAIN
            branch = branch_of(git.cwd)
            if not branch or branch in PROTECTED:
                return MAIN
    return None


WRAPPERS = {"env", "command", "exec", "nice", "nohup", "time", "sudo", "doas", "timeout", "stdbuf"}


def unwrap(tokens: list[str]) -> list[str]:
    """Drop leading VAR=value assignments and wrapper commands (env, nice, timeout 10, ...)."""
    while tokens:
        head = tokens[0].rsplit("/", 1)[-1]
        if re.fullmatch(r"\w+=.*", tokens[0]):
            tokens = tokens[1:]
        elif head in WRAPPERS:
            tokens = tokens[1:]
            while tokens and (tokens[0].startswith("-") or re.fullmatch(r"[\d.]+[smhd]?|\w+=.*", tokens[0])):
                tokens = tokens[1:]  # the wrapper's own options and arguments (timeout 10, env -i A=1)
        else:
            break
    return tokens


def segments(command: str) -> list[list[str]]:
    """Tokenise with shell quoting and split at operators (;, &&, ||, |, &) outside quotes.
    Raises ValueError on unbalanced quotes."""
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    parts: list[list[str]] = [[]]
    for token in lexer:
        if token and set(token) <= set(";&|"):
            parts.append([])
        else:
            parts[-1].append(token)
    return [p for p in parts if p]


def git_pushes_in(tokens: list[str]) -> int:
    """Count `push` tokens that follow a git token in one segment, wherever the git token sits
    (after `then`, inside `$(git`, after a backtick): the pushes the parser must account for."""
    count = 0
    for i, token in enumerate(tokens):
        if not re.search(r"(^|[/`(])git$", token):
            continue
        j = i + 1  # skip git's global options to reach its subcommand
        while j < len(tokens) and tokens[j].startswith("-"):
            j += 2 if tokens[j] in GIT_VALUE_OPTIONS else 1
        if j < len(tokens) and tokens[j].rstrip(")`") == "push":
            count += 1
    return count


def judge(command: str, depth: int = 0) -> str | None:
    """The reason to deny a git operation in the command line, or None."""
    try:
        parts = segments(command)
    except ValueError:
        return UNPARSEABLE if re.search(r"\bgit\b.*\bpush\b", command) else None
    context_changed = False
    for tokens in parts:
        part = " ".join(tokens)
        tokens = unwrap(tokens)
        if tokens and tokens[0] == "eval" and depth < 3:
            if reason := judge(" ".join(tokens[1:]), depth + 1):
                return reason
            continue
        if tokens and tokens[0].rsplit("/", 1)[-1] in SHELLS:
            # sh -c 'script', bash -lc 'script', bash -ec 'script': the script follows the flags.
            flags = [i for i, t in enumerate(tokens[1:], 1) if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", t)]
            if flags and flags[0] + 1 < len(tokens) and depth < 3:
                if reason := judge(tokens[flags[0] + 1], depth + 1):
                    return reason
                continue
        git = parse_git(tokens)
        if git is None or (git.subcommand != "push" and git_pushes_in(tokens)):
            # Fail closed: a push the parser can't reach (if/then, loops, $(...), backticks,
            # functions, a shell without -c) is refused rather than allowed by omission.
            if git_pushes_in(tokens):
                return UNPARSEABLE
            if CONTEXT_CHANGERS.search(part):
                context_changed = True
            continue
        if git.subcommand in {"commit", "merge", "rebase", "am", "cherry-pick"} and "--no-verify" in git.args:
            return NO_VERIFY
        # For commit only, -n is --no-verify, alone or in a cluster such as -nm (for push it's --dry-run).
        if git.subcommand == "commit" and any(re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", a) for a in git.args):
            return NO_VERIFY
        if git.subcommand == "push":
            if git_pushes_in(tokens) > 1:
                return UNPARSEABLE
            if reason := judge_push(git, context_changed):
                return reason
        elif git.subcommand in {"switch", "checkout", "worktree"}:
            context_changed = True
    return None


def decide(command: str) -> tuple[str, str] | None:
    if reason := judge(command):
        return "deny", reason
    for pattern, reason in DENY_TEXT:
        if re.search(pattern, command):
            return "deny", reason
    for pattern, reason in ASK_TEXT:
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
