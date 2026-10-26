"""The rendered project: files, settings and answers the base layer promises."""

from __future__ import annotations

import json
import os
import re
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
    deny = data["permissions"]["deny"]
    assert "Read(./**/.env)" in deny and "Read(./**/.env.production)" in deny
    # .env.example is what AGENTS.md tells agents to read, and an allow rule can't override a deny.
    assert not any(rule.startswith("Read(./.env.*)") for rule in deny)


def hook_entries(data: dict) -> list[tuple[str, dict]]:
    return [(event, h) for event, groups in data["hooks"].items() for g in groups for h in g["hooks"]]


def test_every_hook_runs_in_exec_form_and_its_script_exists(render):
    # Exec form passes the path as one argument, so a project path with spaces still works
    # (https://code.claude.com/docs/en/hooks.md, "Exec form and shell form").
    project = render()
    entries = hook_entries(settings(project))
    assert len(entries) == 3
    for _, hook in entries:
        assert hook["command"] == "python3"
        (script,) = hook["args"]
        path = project / script.replace("${CLAUDE_PROJECT_DIR}/", "")
        assert path.is_file(), script
        assert os.access(path, os.X_OK), f"{script} is not executable"


def test_guard_hooks_fail_closed_and_the_stop_hook_fails_open(render):
    entries = hook_entries(settings(render()))
    on_failure = {hook["args"][0].rsplit("/", 1)[-1]: hook.get("onFailure") for _, hook in entries}
    assert on_failure == {"guard-bash.py": "block", "guard-files.py": "block", "stop-checks.py": None}


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
    for target in ("help", "install", "check", "check-fast", "template-status"):
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


def test_file_guard_also_covers_reads(render):
    matchers = [g["matcher"] for g in settings(render())["hooks"]["PreToolUse"]]
    assert "Edit|Write|NotebookEdit|Read|Grep" in matchers


def test_make_check_skips_the_commit_to_main_guard(render):
    # Fallback review on PR 1: no-commit-to-branch fails on main, so make check failed in CI on main.
    makefile = (render() / "Makefile").read_text()
    assert "SKIP=no-commit-to-branch pre-commit run --all-files" in makefile


# Layers that ship a compose file. Compose has no optional include, so listing a file no layer
# creates (a dotnet one, today) breaks every `docker compose` command in the project.
LAYER_COMPOSE_FILES = {"fastapi": "backend/compose.yaml", "nextjs": "frontend/compose.yaml"}


@pytest.mark.parametrize(
    "stacks",
    [["fastapi", "nextjs"], ["fastapi"], ["fastapi", "dotnet"], ["nextjs"], ["nextjs", "dotnet"]],
)
def test_root_compose_includes_only_files_a_layer_ships(render, stacks):
    compose = yaml.safe_load((render(stacks=stacks) / "compose.yaml").read_text())
    expected = [LAYER_COMPOSE_FILES[s] for s in stacks if s in LAYER_COMPOSE_FILES]
    assert compose == {"name": "course-lens", "include": expected}


@pytest.mark.parametrize("stacks", [[], ["dotnet"]])
def test_no_root_compose_without_a_layer_that_ships_one(render, stacks):
    project = render(stacks=stacks)
    assert not (project / "compose.yaml").exists()
    assert "compose.yaml" not in (project / ".github/template-owned/base.txt").read_text()


def test_nextjs_projects_get_the_devtools_mcp_server_pinned_and_quiet(render):
    project = render(stacks=["fastapi", "nextjs"])
    servers = json.loads((project / ".mcp.json").read_text())["mcpServers"]
    devtools = servers["next-devtools"]
    assert devtools["command"] == "npx"
    package = devtools["args"][-1]
    assert re.fullmatch(r"next-devtools-mcp@\d+\.\d+\.\d+", package), "pin an exact version"
    assert devtools["env"] == {"NEXT_TELEMETRY_DISABLED": "1"}
    assert ".mcp.json" in (project / ".github/template-owned/base.txt").read_text()


@pytest.mark.parametrize("stacks", [["fastapi"], ["dotnet"], []])
def test_no_mcp_config_without_nextjs(render, stacks):
    project = render(stacks=stacks)
    assert not (project / ".mcp.json").exists()
    assert ".mcp.json" not in (project / ".github/template-owned/base.txt").read_text()
