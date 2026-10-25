"""The rendered workflows: hardened as .claude/rules/github-workflows.md says, and shaped by the answers."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d")


def workflows(project: Path) -> dict[str, dict]:
    return {p.name: yaml.safe_load(p.read_text()) for p in (project / ".github" / "workflows").glob("*.yml")}


def uses_lines(project: Path) -> list[str]:
    lines = []
    for path in (project / ".github" / "workflows").glob("*.yml"):
        lines += [ln.split("uses:", 1)[1].strip() for ln in path.read_text().splitlines()
                  if ln.strip().startswith(("uses:", "- uses:")) and "./.github/" not in ln]
    return lines


def test_every_action_is_pinned_to_a_full_sha_with_its_version(render):
    lines = uses_lines(render())
    assert lines
    for line in lines:
        assert SHA_PIN.match(line), line


def test_workflows_grant_nothing_at_the_top_and_time_out_every_job(render):
    for name, wf in workflows(render()).items():
        assert wf["permissions"] == {}, name
        for job_name, job in wf["jobs"].items():
            assert "timeout-minutes" in job, f"{name}:{job_name}"
            assert "permissions" in job, f"{name}:{job_name}"


def test_checkout_never_persists_credentials(render):
    for name, wf in workflows(render()).items():
        for job in wf["jobs"].values():
            for step in job.get("steps", []):
                if "actions/checkout@" in step.get("uses", ""):
                    assert step["with"]["persist-credentials"] is False, name


def test_codeql_languages_follow_the_stacks(render):
    def languages(**data):
        return workflows(render(**data))["codeql.yml"]["jobs"]["analyze"]["strategy"]["matrix"]["language"]

    assert languages() == ["actions", "python", "javascript-typescript"]


def test_codeql_for_a_dotnet_only_project(render):
    wf = workflows(render(stacks=["dotnet"]))
    assert wf["codeql.yml"]["jobs"]["analyze"]["strategy"]["matrix"]["language"] == ["actions", "csharp"]
    steps = [s.get("name") for s in wf["ci.yml"]["jobs"]["check"]["steps"]]
    assert "Install .NET" in steps and "Install Node.js" not in steps


def test_sharp_licence_exception_only_with_nextjs(render):
    with_next = workflows(render())["dependency-review.yml"]["jobs"]["dependency-review"]["steps"][1]["with"]
    assert "sharp-libvips-linux-x64" in with_next["allow-dependencies-licenses"]


def test_no_sharp_exception_without_nextjs(render):
    step = workflows(render(stacks=["fastapi"]))["dependency-review.yml"]["jobs"]["dependency-review"]["steps"][1]
    assert "allow-dependencies-licenses" not in step["with"]


def test_publish_image_is_optional_and_attests_provenance_and_sbom(render):
    wf = workflows(render())["publish-image.yml"]
    steps = wf["jobs"]["publish"]["steps"]
    attests = [s for s in steps if "actions/attest@" in s.get("uses", "")]
    assert [("sbom-path" in s["with"]) for s in attests] == [False, True]
    assert all(s["with"]["push-to-registry"] is True for s in attests)
    assert "gh attestation verify" in steps[-1]["run"]


def test_no_publish_workflow_without_container_images(render):
    project = render(container_images=False)
    assert "publish-image.yml" not in workflows(project)
    assert "publish-image" not in (project / ".github" / "template-owned" / "base.txt").read_text()


def test_owned_list_matches_the_files_base_renders(render):
    project = render()
    patterns = [ln for ln in (project / ".github" / "template-owned" / "base.txt").read_text().splitlines()
                if ln and not ln.startswith("#")]
    for pattern in patterns:
        assert list(project.glob(pattern)), f"{pattern} is listed but not rendered"


@pytest.mark.skipif(not shutil.which("docker") and not shutil.which("uvx"), reason="needs uvx for zizmor")
def test_zizmor_pedantic_finds_nothing_in_the_rendered_workflows(render):
    project = render()
    result = subprocess.run(["uvx", "zizmor@1.31.1", "--persona=pedantic", "--offline", "--no-progress",
                             str(project / ".github" / "workflows")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


ACTIONLINT = "rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"


@pytest.mark.skipif(not shutil.which("docker"), reason="needs docker for actionlint")
@pytest.mark.parametrize("stacks", [["fastapi", "nextjs"], ["dotnet"], ["fastapi"]])
def test_actionlint_passes_for_each_stack_combination(render, stacks):
    project = render(stacks=stacks)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    result = subprocess.run(["docker", "run", "--rm", "-v", f"{project}:/repo", "-w", "/repo", ACTIONLINT],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_image_names_are_lowercase_even_when_the_owner_has_capitals(render):
    # Codex review on PR 5: registry paths must be lowercase, and github.repository keeps capitals.
    wf = workflows(render(github_org="ExampleOrg"))["publish-image.yml"]
    image = wf["jobs"]["publish"]["env"]["IMAGE"]
    assert image == "ghcr.io/exampleorg/course-lens-${{ inputs.image }}"


def test_workflows_that_read_secrets_run_in_a_dedicated_environment(render):
    # zizmor's secrets-outside-env: a token read by a job belongs to an environment with its own rules.
    job = workflows(render())["template-update.yml"]["jobs"]["update"]
    assert job["environment"] == "template-update"


def test_template_update_uses_a_token_for_prs_and_falls_back_to_an_issue(render):
    job = workflows(render())["template-update.yml"]["jobs"]["update"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}  # GITHUB_TOKEN never pushes or opens PRs
    steps = {s["name"]: s for s in job["steps"]}
    assert "env.UPDATE_TOKEN != ''" in steps["Open the pull request"]["if"]
    assert 'GH_TOKEN="$UPDATE_TOKEN" gh pr create' in steps["Open the pull request"]["run"]
    assert "env.UPDATE_TOKEN == ''" in steps["Report the update without a token"]["if"]
    assert "gh issue create" in steps["Report the update without a token"]["run"]
