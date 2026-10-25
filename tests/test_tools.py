"""Helper scripts the rendered project runs from pre-commit and make."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


def test_rej_check_finds_ignored_leftovers_and_skips_dependency_folders(render):
    project = render()
    script = project / "tools" / "check_no_rej.py"
    clean = subprocess.run([sys.executable, str(script)], cwd=project, capture_output=True, text=True)
    assert clean.returncode == 0

    (project / "node_modules" / "pkg").mkdir(parents=True)
    (project / "node_modules" / "pkg" / "x.rej").write_text("vendored\n")
    assert subprocess.run([sys.executable, str(script)], cwd=project).returncode == 0

    (project / "Makefile.rej").write_text("@@ rejected hunk\n")
    dirty = subprocess.run([sys.executable, str(script)], cwd=project, capture_output=True, text=True)
    assert dirty.returncode == 1
    assert "Makefile.rej" in dirty.stdout


def test_rej_hook_always_runs_because_gitignore_hides_rej_files(render):
    project = render()
    hooks = {h["id"]: h for repo in yaml.safe_load((project / ".pre-commit-config.yaml").read_text())["repos"]
             for h in repo["hooks"]}
    rej = hooks["no-rej-files"]
    assert rej["always_run"] is True and rej["pass_filenames"] is False
    assert "*.rej" in (project / ".gitignore").read_text().splitlines()
    assert (project / Path(rej["entry"].split()[-1])).is_file()


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=project, check=True,
                   capture_output=True)


def test_template_owned_check_warns_on_owned_files_and_never_fails(render):
    project = render()
    _git(project, "init", "-q", "-b", "main")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "start")
    _git(project, "switch", "-q", "-c", "feat/x")
    (project / "AGENTS.md").write_text((project / "AGENTS.md").read_text() + "\nA local rule.\n")
    (project / ".claude" / "hooks" / "guard-bash.py").write_text("# changed\n")
    (project / "app.py").write_text("x = 1\n")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "change")
    run = subprocess.run([sys.executable, "tools/check_template_owned.py", "--base", "main"], cwd=project,
                         capture_output=True, text=True)
    assert run.returncode == 0
    warned = [line for line in run.stdout.splitlines() if line.startswith("::warning")]
    assert len(warned) == 2
    assert any("file=AGENTS.md" in w and "house-template-base" in w for w in warned)
    assert any("file=.claude/hooks/guard-bash.py" in w for w in warned)
    assert not any("app.py" in w for w in warned)
