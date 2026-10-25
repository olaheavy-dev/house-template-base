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
    ("if true; then git push origin HEAD:main; fi", "deny"),  # pushes the parser can't reach
    ("for b in x; do git push origin $b; done", "deny"),
    ("echo $(git push origin main)", "deny"),
    ("echo `git push origin main`", "deny"),
    ("git commit -m 'fix: push the button'", "allow"),  # the word push in a message
    ("git log --grep push", "allow"),
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
    assert bash_decision(f"git -C {other} push origin HEAD", here) == "deny"
    assert bash_decision(f"git -C {here} push origin HEAD", other) == "allow"


def test_guard_bash_refuses_a_bare_push_even_from_a_feature_branch(git_repo):
    # A bare push follows push.default and remote.<name>.push (Codex: HEAD:main is valid config),
    # so agents always name the branch.
    repo = git_repo("feat/x")
    assert bash_decision("git push", repo) == "deny"
    assert bash_decision("git push origin", repo) == "deny"


@pytest.mark.parametrize(("command", "expected"), [
    ("git push origin :", "deny"),  # matching branches, main included
    ("git push origin 'refs/heads/*:refs/heads/*'", "deny"),
    ("git push origin 'feat/*'", "deny"),
    ("git push origin feat/x:feat/x", "allow"),
    ("git commit -n -m 'feat: x'", "deny"),  # -n is commit's short --no-verify
    ("git commit -nm 'feat: x'", "deny"),
    ("git commit -am 'feat: x'", "allow"),
    ("git push -n origin feat/x", "allow"),  # for push, -n is --dry-run
    ("git push -uf origin feat/x", "deny"),  # force inside combined short options
    ("git push -fu origin feat/x", "deny"),
    ("git push -u origin feat/x -f", "deny"),
    ("git push --force-if-includes origin feat/x", "deny"),
    ("git push -o ci.skip origin feat/x", "deny"),  # allow-list: unusual flags are refused
    ("git push --repo=origin feat/x", "deny"),
    ("git push --delete origin feat/x", "deny"),
    ("git push origin refs/tags/v1:refs/tags/v1", "deny"),
    ("git push origin v1..v2", "deny"),
    ("git push -u origin HEAD", "allow"),  # current branch is feat/x
    ("git push origin HEAD:feat/y", "allow"),
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


@pytest.mark.parametrize(("tool", "key", "path", "expected"), [
    # Fallback review on PR 1: a fixed deny list missed .env.prod, .env.backup and backend/.env.
    ("Read", "file_path", ".env", "deny"),
    ("Read", "file_path", ".env.prod", "deny"),
    ("Read", "file_path", ".env.backup", "deny"),
    ("Read", "file_path", "backend/.env", "deny"),
    ("Read", "file_path", "backend/.env.local.bak", "deny"),
    ("Read", "file_path", ".env.example", "allow"),
    ("Read", "file_path", "secrets/token.txt", "deny"),
    ("Read", "file_path", ".copier-answers.base.yml", "allow"),  # read yes, edit no
    ("Grep", "path", "backend/.env", "deny"),
    ("Grep", "path", "backend", "allow"),
    ("Read", "file_path", ".ENV", "deny"),  # case-insensitive filesystems
    ("Read", "file_path", ".Env.Prod", "deny"),
    ("Read", "file_path", "deploy/Server.PEM", "deny"),
    ("Read", "file_path", ".env.Example", "allow"),
])
def test_guard_files_on_reads(tmp_path, tool, key, path, expected):
    out = run_hook("guard-files.py", {"tool_name": tool, "tool_input": {key: f"/repo/{path}"}}, tmp_path)
    assert ("deny" if out else "allow") == expected


@pytest.mark.parametrize(("glob", "expected"), [
    # Re-review on PR 1: an explicit glob makes ripgrep search ignored and hidden files.
    (".env*", "deny"),
    ("*", "deny"),
    ("*backup", "deny"),
    ("*.pem", "deny"),
    ("*.py", "allow"),
    ("**/*.ts", "allow"),
    ("*.{md,txt}", "allow"),
])
def test_guard_files_on_grep_globs(tmp_path, glob, expected):
    event = {"tool_name": "Grep", "tool_input": {"pattern": "KEY", "path": "/repo", "glob": glob}}
    out = run_hook("guard-files.py", event, tmp_path)
    assert ("deny" if out else "allow") == expected




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


def _with_remote(repo: Path, tmp_path: Path) -> None:
    remote = tmp_path / f"{repo.name}-remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "-u", "origin", "HEAD"], cwd=repo, check=True)


def test_stop_hook_checks_commits_made_during_the_turn(git_repo, tmp_path):
    # Codex review on PR 1: an agent that commits leaves git status clean.
    repo = git_repo("feat/x")
    _project_with_check(repo, "@echo 'types: 1 error' && exit 1")
    _with_remote(repo, tmp_path)
    (repo / "new.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "wip"], cwd=repo, check=True)
    out = run_hook("stop-checks.py", {"hook_event_name": "Stop", "stop_hook_active": False}, repo)
    assert out and out["decision"] == "block" and "types: 1 error" in out["reason"]


def test_stop_hook_does_nothing_without_changes(git_repo, tmp_path):
    repo = git_repo("feat/x")
    _project_with_check(repo, "@exit 1")
    _with_remote(repo, tmp_path)  # everything pushed: nothing new to check
    assert run_hook("stop-checks.py", {"hook_event_name": "Stop", "stop_hook_active": False}, repo) is None


def test_stop_hook_ignores_pushed_commits_when_the_upstream_is_main(git_repo, tmp_path):
    # Re-review on PR 1: a branch started from origin/main tracks it, so pushed work looks "ahead".
    repo = git_repo("main")
    _project_with_check(repo, "@exit 1")
    _with_remote(repo, tmp_path)
    subprocess.run(["git", "switch", "-q", "-c", "feat/x", "--track", "origin/main"], cwd=repo, check=True)
    (repo / "x.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x"], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "feat/x"], cwd=repo, check=True)
    assert run_hook("stop-checks.py", {"hook_event_name": "Stop", "stop_hook_active": False}, repo) is None


def test_stop_hook_ignores_old_commits_in_a_repository_with_no_remote(git_repo):
    # Fallback review on PR 1: before the first push every commit is "unpushed".
    repo = git_repo("feat/x")
    _project_with_check(repo, "@exit 1")
    assert run_hook("stop-checks.py", {"hook_event_name": "Stop", "stop_hook_active": False}, repo) is None


def test_stop_hook_never_blocks_twice_in_a_row(git_repo):
    repo = git_repo("feat/x")
    _project_with_check(repo, "@exit 1")
    (repo / "new.py").write_text("x = 1\n")
    assert run_hook("stop-checks.py", {"hook_event_name": "Stop", "stop_hook_active": True}, repo) is None


def test_guard_bash_requires_a_destination_when_the_remote_maps_pushes(git_repo):
    # Codex review on PR 1: remote.origin.push=refs/heads/feat/x:refs/heads/main sends a
    # source-only push to main.
    repo = git_repo("feat/x")
    subprocess.run(["git", "config", "remote.origin.push", "refs/heads/feat/x:refs/heads/main"], cwd=repo, check=True)
    assert bash_decision("git push origin feat/x", repo) == "deny"
    assert bash_decision("git push -u origin HEAD", repo) == "deny"
    assert bash_decision("git push origin feat/x:feat/x", repo) == "allow"
    assert bash_decision("git push origin feat/x:main", repo) == "deny"


def test_nested_shells_inherit_a_directory_change(git_repo):
    # Codex review on PR 1: cd <main worktree> && bash -c 'git push origin HEAD' runs in main.
    here, other = git_repo("feat/x"), git_repo("main")
    assert bash_decision(f"cd {other} && bash -c 'git push origin HEAD'", here) == "deny"
    assert bash_decision(f"cd {other} && git push origin feat/x", here) == "deny"
    assert bash_decision(f"cd {other} && git push origin feat/x:feat/x", here) == "allow"
    assert bash_decision("git switch feat/y && bash -c 'git push origin HEAD'", here) == "deny"
