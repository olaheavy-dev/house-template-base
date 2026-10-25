"""`copier update` between two tagged template versions: the path every project takes to get improvements.

Copier updates from git tags (https://copier.readthedocs.io/en/stable/updating/), so the test clones the
template into a scratch repository, tags v0.1.0, renders a project there, changes the template and
tags v0.2.0, then updates the project and checks that the change arrives and local work survives.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import copier
import yaml

from conftest import DEFAULTS, ROOT


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


def template_at_v010(tmp_path: Path) -> Path:
    """A scratch copy of the template, including uncommitted changes, committed and tagged v0.1.0."""
    template = tmp_path / "template-repo"
    # No tags from this repository's real releases: the test makes its own v0.1.0 and v0.2.0.
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", "--no-tags", str(ROOT), str(template)], check=True)
    for tag in git(template, "tag", "--list").split():
        git(template, "tag", "-d", tag)
    for path in subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--modified"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.split():
        (template / path).parent.mkdir(parents=True, exist_ok=True)
        (template / path).write_bytes((ROOT / path).read_bytes())
    git(template, "add", "-A")
    git(template, "commit", "-q", "--allow-empty", "-m", "scratch")
    git(template, "tag", "v0.1.0")
    return template


def test_update_brings_template_changes_and_keeps_local_work(tmp_path):
    template = template_at_v010(tmp_path)
    project = tmp_path / "project"
    copier.run_copy(str(template), project, data=DEFAULTS, defaults=True, unsafe=True, quiet=True, vcs_ref="v0.1.0")
    git(project, "init", "-q", "-b", "main")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "start")

    # Local work: an edit to a template-owned file (merged, not overwritten), and a rule of its own.
    gitignore = project / ".gitignore"
    gitignore.write_text(gitignore.read_text() + "\n# Local\nlocal-cache/\n")
    (project / ".claude" / "rules" / "product.md").write_text("---\npaths: [\"src/**\"]\n---\n\nProduct rule.\n")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "local work")

    # The template moves on: a new rule in AGENTS.md, released as v0.2.0.
    agents = template / "template" / "AGENTS.md.jinja"
    agents.write_text(agents.read_text().replace(
        "7. **Enforced, not only written.**", "7. **New template rule.** Added in v0.2.0.\n8. **Enforced, not only written.**"))
    git(template, "commit", "-q", "-am", "feat: a new rule")
    git(template, "tag", "v0.2.0")

    # What the weekly template-update workflow and `make template-status` rely on: exit 2 = update available.
    check = subprocess.run([sys.executable, "-m", "copier", "check-update", "--quiet", "--answers-file",
                            ".copier-answers.base.yml"], cwd=project, capture_output=True, text=True)
    assert check.returncode == 2, check.stdout + check.stderr

    copier.run_update(project, answers_file=".copier-answers.base.yml", defaults=True, unsafe=True, quiet=True,
                      overwrite=True, skip_answered=True)

    assert "**New template rule.** Added in v0.2.0." in (project / "AGENTS.md").read_text()
    assert "local-cache/" in gitignore.read_text()
    assert (project / ".claude" / "rules" / "product.md").exists()
    answers = yaml.safe_load((project / ".copier-answers.base.yml").read_text())
    assert answers["_commit"] == "v0.2.0"
    leftovers = [p for p in project.rglob("*.rej") if ".git" not in p.parts]
    assert not leftovers
    assert "<<<<<<<" not in (project / "AGENTS.md").read_text()


def test_this_repositorys_required_checks_are_jobs_its_workflows_run():
    import json
    import yaml as _yaml
    rules = {r["type"]: r for r in json.loads((ROOT / ".github" / "rulesets" / "main.json").read_text())["rules"]}
    required = {c["context"] for c in rules["required_status_checks"]["parameters"]["required_status_checks"]}
    names = set()
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        wf = _yaml.safe_load(path.read_text())
        triggers = wf[True] if True in wf else wf["on"]
        if "pull_request" not in triggers:
            continue
        for job in wf["jobs"].values():
            name = job["name"]
            if "${{ matrix.language }}" in name:
                names |= {name.replace("${{ matrix.language }}", lang) for lang in job["strategy"]["matrix"]["language"]}
            else:
                names.add(name)
    assert required <= names, required - names
