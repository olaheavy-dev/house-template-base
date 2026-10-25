"""Shared fixtures: render the template into a temporary project with Copier's Python API."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import copier
import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "template" / ".claude" / "hooks"

DEFAULTS = {
    "project_name": "Course Lens",
    "description": "Turns a course into something you can search, question and practise.",
    "domain": "courselens.example.dev",
}


@pytest.fixture
def render(tmp_path: Path) -> Callable[..., Path]:
    """Render the template (including uncommitted changes) with DEFAULTS plus overrides."""

    def _render(**data: object) -> Path:
        dst = tmp_path / "project"
        copier.run_copy(str(ROOT), dst, data={**DEFAULTS, **data}, defaults=True, unsafe=True,
                        quiet=True, vcs_ref="HEAD")
        return dst

    return _render


@pytest.fixture
def git_repo(tmp_path: Path) -> Callable[[str], Path]:
    """An empty git repository checked out on the given branch, for hooks that ask git."""

    def _repo(branch: str = "main") -> Path:
        repo = tmp_path / f"repo-{branch.replace('/', '-')}"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", branch], cwd=repo, check=True)
        return repo

    return _repo
