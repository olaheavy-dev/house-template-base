"""The guardrail hooks, fed the event JSON Claude Code sends (https://code.claude.com/docs/en/hooks.md)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import HOOKS


def run_hook(name: str, event: dict, cwd: Path) -> dict | None:
    result = subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(event),
                            capture_output=True, text=True, cwd=cwd, timeout=60, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def bash_decision(command: str, cwd: Path) -> str:
    out = run_hook("guard-bash.py", {"tool_name": "Bash", "tool_input": {"command": command}}, cwd)
    return out["hookSpecificOutput"]["permissionDecision"] if out else "allow"


ON_A_FEATURE_BRANCH = [
    ("git push -u origin feat/agent-workflow", "allow"),
    ("make check && git push origin feat/x", "allow"),
    ("git push origin main", "deny"),
    ("git push origin HEAD:main", "deny"),
    ("git push origin feat/x:refs/heads/main", "deny"),
    ("sh -c 'git push origin feat/x:main'", "deny"),
    ("git push --force origin feat/x", "deny"),
    ("git push --force-with-lease origin feat/x", "deny"),
    ("git push origin +feat/x", "deny"),
    ("git push --all origin", "deny"),
    ("git push --mirror origin", "deny"),
    ("git push --prune origin feat/x", "deny"),
    ("git push --tags origin", "allow"),
    ("git commit --no-verify -m 'feat: x'", "deny"),
    ("git commit -m 'feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>'", "deny"),
    ("gh pr create --body 'Generated with [Claude Code](https://claude.com/claude-code)'", "deny"),
    ("cat .env", "deny"),
    ("source .env.local", "deny"),
    ("cat .env.example", "allow"),
    ("git reset --hard HEAD~1", "ask"),
    ("git clean -fd", "ask"),
    ("git checkout -- .", "ask"),
    ("make check", "allow"),
    ("git commit -m 'feat: co-authored docs'", "allow"),
]


@pytest.mark.parametrize(("command", "expected"), ON_A_FEATURE_BRANCH)
def test_guard_bash_on_a_feature_branch(git_repo, command, expected):
    assert bash_decision(command, git_repo("feat/x")) == expected


@pytest.mark.parametrize("command", ["git push", "git -C . push", "git push origin", "git push origin HEAD"])
def test_guard_bash_denies_a_bare_push_from_main(git_repo, command):
    assert bash_decision(command, git_repo("main")) == "deny"


def test_guard_bash_reads_the_branch_of_the_repository_git_c_points_at(git_repo):
    # Codex review on PR 1: -C changes the repository within one git invocation.
    here, other = git_repo("feat/x"), git_repo("main")
    assert bash_decision(f"git -C {other} push origin", here) == "deny"
    assert bash_decision(f"git -C {here} push origin", other) == "allow"


def test_guard_bash_allows_a_bare_push_from_a_feature_branch(git_repo):
    assert bash_decision("git push", git_repo("feat/x")) == "allow"


@pytest.mark.parametrize(("command", "expected"), [
    ("git commit -n -m 'feat: x'", "deny"),  # -n is commit's short --no-verify
    ("git commit -nm 'feat: x'", "deny"),
    ("git commit -am 'feat: x'", "allow"),
    ("git push -n origin feat/x", "allow"),  # for push, -n is --dry-run
    ("git push -uf origin feat/x", "deny"),  # force inside combined short options
    ("git push -fu origin feat/x", "deny"),
    ("git push -u origin feat/x -f", "deny"),
    ("git push --force-if-includes origin feat/x", "deny"),
    ("git push -o ci.skip origin feat/x", "allow"),  # -o takes a value; not a refspec
    ("git push --repo=origin feat/x", "allow"),
    ("FOO=1 git push origin main", "deny"),
    ("bash -lc 'git push origin main'", "deny"),
    ("zsh -ec 'git push --force origin feat/x'", "deny"),
    ("env GIT_TRACE=1 git push origin main", "deny"),
    ("timeout 30 git push origin main", "deny"),
    ("command git push -f origin feat/x", "deny"),
    ("eval 'git push origin main'", "deny"),
    ("nice -n 10 git push origin feat/x", "allow"),
    ("bash -c 'git push origin feat/x:main'", "deny"),
    ("git commit -m 'fix: a; b && c' && git push origin feat/x", "allow"),  # operators inside quotes
    ("git push origin 'feat/x", "deny"),  # unbalanced quotes: fail closed
    ("git --git-dir=../other/.git push origin", "deny"),
    ("git --work-tree ../other push", "deny"),
    ("git switch main && git push origin", "deny"),
    ("git checkout main; git push", "deny"),
    ("cd ../other-repo && git push", "deny"),
    ("git switch feat/y && git push origin feat/y", "allow"),  # a named branch is known
    ("git switch -c feat/y && git push -u origin feat/y", "allow"),
])
def test_guard_bash_fails_closed_when_a_branch_change_precedes_a_bare_push(git_repo, command, expected):
    # The hook runs before the command, so it can't see which branch a bare push will run from.
    assert bash_decision(command, git_repo("feat/x")) == expected


@pytest.mark.parametrize(("path", "expected"), [
    (".env", "deny"),
    ("config/.env.production", "deny"),
    (".env.example", "allow"),
    ("secrets/token.txt", "deny"),
    ("deploy/server.pem", "deny"),
    (".copier-answers.base.yml", "deny"),
    (".copier-answers.fastapi.yml", "deny"),
    ("backend/app/main.py", "allow"),
    ("docs/secrets-handling.md", "allow"),
])
def test_guard_files(tmp_path, path, expected):
    out = run_hook("guard-files.py", {"tool_name": "Edit", "tool_input": {"file_path": f"/repo/{path}"}}, tmp_path)
    assert ("deny" if out else "allow") == expected
    if out:
        assert out["hookSpecificOutput"]["permissionDecisionReason"]


def _project_with_check(repo: Path, recipe: str) -> None:
    (repo / "Makefile").write_text(f"check-fast:\n\t{recipe}\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   cwd=repo, check=True)


def test_stop_hook_blocks_when_check_fast_fails_on_changes(git_repo):
    repo = git_repo("feat/x")
    _project_with_check(repo, "@echo 'lint: 2 errors' && exit 1")
    (repo / "new.py").write_text("x = 1\n")
    out = run_hook("stop-checks.py", {"hook_event_name": "Stop", "stop_hook_active": False}, repo)
    assert out["decision"] == "block"
    assert "lint: 2 errors" in out["reason"]


def test_stop_hook_passes_when_check_fast_passes(git_repo):
    repo = git_repo("feat/x")
    _project_with_check(repo, "@true")
    (repo / "new.py").write_text("x = 1\n")
    assert run_hook("stop-checks.py", {"hook_event_name": "Stop", "stop_hook_active": False}, repo) is None


def test_stop_hook_does_nothing_without_changes(git_repo):
    repo = git_repo("feat/x")
    _project_with_check(repo, "@exit 1")
    assert run_hook("stop-checks.py", {"hook_event_name": "Stop", "stop_hook_active": False}, repo) is None


def test_stop_hook_never_blocks_twice_in_a_row(git_repo):
    repo = git_repo("feat/x")
    _project_with_check(repo, "@exit 1")
    (repo / "new.py").write_text("x = 1\n")
    assert run_hook("stop-checks.py", {"hook_event_name": "Stop", "stop_hook_active": True}, repo) is None
