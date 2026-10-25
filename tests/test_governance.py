"""Repository governance the base layer renders: rulesets, settings script, Dependabot, policy files."""

from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path

import pytest
import yaml


def ruleset(project: Path) -> dict:
    return json.loads((project / ".github" / "rulesets" / "main.json").read_text())


def required_checks(project: Path) -> set[str]:
    rules = {r["type"]: r for r in ruleset(project)["rules"]}
    return {c["context"] for c in rules["required_status_checks"]["parameters"]["required_status_checks"]}


def pull_request_job_names(project: Path) -> set[str]:
    """The check names jobs report on pull requests, with CodeQL's matrix expanded."""
    names = set()
    for path in (project / ".github" / "workflows").glob("*.yml"):
        wf = yaml.safe_load(path.read_text())
        triggers = wf[True] if True in wf else wf["on"]  # YAML reads a bare `on:` key as True
        if "pull_request" not in triggers:
            continue
        for job in wf["jobs"].values():
            name = job["name"]
            if "${{ matrix.language }}" in name:
                names |= {name.replace("${{ matrix.language }}", lang) for lang in job["strategy"]["matrix"]["language"]}
            else:
                names.add(name)
    return names


@pytest.mark.parametrize("stacks", [["fastapi", "nextjs"], ["dotnet"], ["fastapi"]])
def test_every_required_check_is_a_job_that_runs_on_pull_requests(render, stacks):
    # A required check that no job reports leaves every merge waiting forever.
    project = render(stacks=stacks)
    assert required_checks(project) <= pull_request_job_names(project)


def test_required_checks_include_each_stacks_codeql_language(render):
    checks = required_checks(render(stacks=["fastapi", "dotnet"]))
    assert {"make check", "actionlint", "zizmor", "CodeQL (actions)", "CodeQL (python)", "CodeQL (csharp)"} <= checks
    assert "CodeQL (javascript-typescript)" not in checks


def test_required_workflows_run_on_every_pull_request(render):
    project = render()
    for path in (project / ".github" / "workflows").glob("*.yml"):
        wf = yaml.safe_load(path.read_text())
        triggers = wf[True] if True in wf else wf["on"]
        pr = triggers.get("pull_request") if isinstance(triggers, dict) else None
        assert not (isinstance(pr, dict) and "paths" in pr), f"{path.name} filters pull requests by path"


def test_ruleset_protects_main_and_gates_code_scanning(render):
    rules = {r["type"]: r for r in ruleset(render())["rules"]}
    assert {"deletion", "non_fast_forward", "required_linear_history", "pull_request", "code_scanning"} <= set(rules)
    assert rules["pull_request"]["parameters"]["allowed_merge_methods"] == ["squash"]
    tools = {t["tool"] for t in rules["code_scanning"]["parameters"]["code_scanning_tools"]}
    assert tools == {"CodeQL", "zizmor"}


def test_repo_settings_script_is_valid_bash_aimed_at_this_repository(render):
    project = render(github_org="acme", project_slug="course-lens")
    script = project / "tools" / "apply-repo-settings.sh"
    assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0
    text = script.read_text()
    assert 'REPO="${REPO:-acme/course-lens}"' in text
    assert "sha_pinning_required=true" in text and ".github/rulesets/*.json" in text
    assert "template-candidate" in text


def test_make_repo_settings_runs_the_script(render):
    project = render()
    assert "\nrepo-settings:" in (project / "Makefile").read_text()
    assert "make repo-settings" in (project / "AGENTS.md").read_text()


def test_dependabot_covers_each_stack_and_always_the_workflows_and_hooks(render):
    def ecosystems(**data):
        cfg = yaml.safe_load((render(**data) / ".github" / "dependabot.yml").read_text())
        return {u["package-ecosystem"] for u in cfg["updates"]}

    assert ecosystems() == {"github-actions", "pre-commit", "uv", "npm", "docker"}


def test_dependabot_for_a_dotnet_project_without_images(render):
    cfg = yaml.safe_load((render(stacks=["dotnet"], container_images=False) / ".github" / "dependabot.yml").read_text())
    assert {u["package-ecosystem"] for u in cfg["updates"]} == {"github-actions", "pre-commit", "nuget"}
    assert all(u["cooldown"]["default-days"] == 7 for u in cfg["updates"])


def test_licence_follows_the_answer(render):
    year = str(datetime.date.today().year)
    reserved = (render() / "LICENSE").read_text()
    assert reserved.startswith(f"Copyright (c) {year} Sunkanmi Olawuwo. All rights reserved.")


def test_mit_licence(render):
    mit = (render(license="mit") / "LICENSE").read_text()
    assert mit.startswith("MIT License") and "Sunkanmi Olawuwo" in mit


def test_security_policy_points_to_private_reporting(render):
    text = (render(github_org="acme", project_slug="course-lens") / "SECURITY.md").read_text()
    assert "https://github.com/acme/course-lens/security/advisories/new" in text
    assert "gh attestation verify" in text


def test_security_policy_without_images_has_no_attestation_line(render):
    assert "gh attestation verify" not in (render(container_images=False) / "SECURITY.md").read_text()


def test_issue_forms_disable_blank_issues_and_route_vulnerabilities_privately(render):
    project = render(github_org="acme", project_slug="course-lens")
    config = yaml.safe_load((project / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text())
    assert config["blank_issues_enabled"] is False
    assert config["contact_links"][0]["url"].endswith("acme/course-lens/security/advisories/new")
    for form in ("task.yml", "bug.yml", "decision.yml"):
        assert yaml.safe_load((project / ".github" / "ISSUE_TEMPLATE" / form).read_text())["body"]


def test_pull_request_template_asks_about_upstreaming(render):
    text = (render() / ".github" / "pull_request_template.md").read_text()
    assert "template-candidate" in text and "## Noticed, not changed" in text


def test_readme_badges_and_decision_records(render):
    project = render(github_org="acme", project_slug="course-lens", stacks=["fastapi"])
    readme = (project / "README.md").read_text()
    assert "acme/course-lens/actions/workflows/ci.yml/badge.svg" in readme
    assert "api.scorecard.dev/projects/github.com/acme/course-lens/badge" in readme
    record = (project / "docs" / "decisions" / "0002-start-from-house-template.md").read_text()
    assert "`house-template-base` and `house-template-fastapi`" in record


def test_codeowners_names_the_owner_on_governed_paths(render):
    lines = (render(owner_github="someone") / ".github" / "CODEOWNERS").read_text().splitlines()
    assert "*            @someone" in lines and "/.claude/    @someone" in lines
