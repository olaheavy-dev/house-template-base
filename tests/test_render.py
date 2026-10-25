"""The rendered project: files, settings and answers the base layer promises."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from copier.errors import CopierAnswersInterrupt, UserMessageError


def settings(project: Path) -> dict:
    return json.loads((project / ".claude" / "settings.json").read_text())


def test_claude_md_imports_agents_md_rather_than_being_a_symlink(render):
    project = render()
    claude = project / "CLAUDE.md"
    assert not claude.is_symlink()
    assert claude.read_text() == "@AGENTS.md\n"
    assert "# AGENTS.md" in (project / "AGENTS.md").read_text()


def test_agents_md_carries_the_project_and_the_owner(render):
    text = (render() / "AGENTS.md").read_text()
    assert "Turns a course into something" in text
    assert "https://courselens.example.dev" in text
    assert "@sunkanmi-olawuwo" in text
    assert "TODO" not in text


def test_settings_turn_off_agent_attribution_and_bypass_mode(render):
    data = settings(render())
    assert data["attribution"] == {"commit": "", "pr": "", "sessionUrl": False}
    assert data["permissions"]["disableBypassPermissionsMode"] == "disable"
    assert "Read(./.env)" in data["permissions"]["deny"]


def test_every_hook_in_settings_exists_and_is_executable(render):
    project = render()
    data = settings(project)
    commands = [h["command"] for groups in data["hooks"].values() for g in groups for h in g["hooks"]]
    assert len(commands) == 3
    for command in commands:
        path = project / command.replace("${CLAUDE_PROJECT_DIR}/", "")
        assert path.is_file(), command
        assert os.access(path, os.X_OK), f"{command} is not executable"


def test_agent_kit_is_enabled_from_the_org_marketplace(render):
    data = settings(render(github_org="acme"))
    assert data["extraKnownMarketplaces"]["acme"]["source"] == {"source": "github", "repo": "acme/agent-kit"}
    assert data["enabledPlugins"] == {"agent-kit@acme": True}


def test_without_the_agent_kit_settings_and_rulebook_have_no_plugin(render):
    project = render(agent_kit=False)
    data = settings(project)
    assert "enabledPlugins" not in data and "extraKnownMarketplaces" not in data
    assert "agent-kit:" not in (project / "AGENTS.md").read_text()


def test_path_scoped_rules_have_paths_frontmatter(render):
    rules = sorted((render() / ".claude" / "rules").glob("*.md"))
    assert {r.name for r in rules} >= {"github-workflows.md", "decisions.md", "claude-config.md"}
    for rule in rules:
        front = rule.read_text().split("---")[1]
        assert yaml.safe_load(front)["paths"], rule.name


def test_answers_file_records_the_template_version_for_updates(render):
    answers = yaml.safe_load((render() / ".copier-answers.base.yml").read_text())
    assert answers["_commit"]
    assert answers["project_slug"] == "course-lens"
    assert answers["stacks"] == ["fastapi", "nextjs"]


def test_makefile_exposes_the_documented_targets(render):
    makefile = (render() / "Makefile").read_text()
    for target in ("help", "install", "check", "check-fast", "repo-settings", "template-status"):
        assert f"\n{target}:" in makefile, target
    assert "-include mk/*.mk" in makefile


def test_gitignore_keeps_secrets_and_local_settings_out(render):
    ignored = (render() / ".gitignore").read_text().splitlines()
    for entry in (".env", "!.env.example", ".claude/settings.local.json", "*.rej"):
        assert entry in ignored


@pytest.mark.parametrize("slug", ["Course Lens", "1course", "course_lens"])
def test_invalid_slugs_are_refused(render, slug):
    with pytest.raises((ValueError, UserMessageError, CopierAnswersInterrupt)):
        render(project_slug=slug)
