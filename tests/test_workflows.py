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


def test_published_images_get_the_commit_they_were_built_from(render):
    # The web image reports it on /health/live (house-template-nextjs).
    steps = workflows(render())["publish-image.yml"]["jobs"]["publish"]["steps"]
    build = next(s for s in steps if s.get("id") == "build")
    assert build["with"]["build-args"].splitlines() == ["GIT_COMMIT=${{ github.sha }}"]


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
    # GITHUB_TOKEN never pushes or opens PRs; it reads PRs (Codex review on PR 12) and opens issues.
    assert job["permissions"] == {"contents": "read", "pull-requests": "read", "issues": "write"}
    steps = {s["name"]: s for s in job["steps"]}
    assert "env.UPDATE_TOKEN != ''" in steps["Open the pull request"]["if"]
    assert 'GH_TOKEN="$UPDATE_TOKEN" gh pr create' in steps["Open the pull request"]["run"]
    assert "env.UPDATE_TOKEN == ''" in steps["Report the update without a token"]["if"]
    assert "gh issue create" in steps["Report the update without a token"]["run"]


def test_a_notification_issue_does_not_block_the_update_once_a_token_exists(render):
    # From a Codex review in a generated project: an open "update available" issue kept every later run skipping.
    steps = {s["name"]: s for s in workflows(render())["template-update.yml"]["jobs"]["update"]["steps"]}
    condition = steps["Apply new template versions"]["if"]
    assert "steps.open.outputs.prs == '0'" in condition
    assert "env.UPDATE_TOKEN != '' || steps.open.outputs.issues == '0'" in condition
    assert "gh issue close" in steps["Open the pull request"]["run"]


def test_ci_installs_pnpm_without_corepack_for_nextjs(render):
    # Corepack no longer ships with Node from 25 (the node:26 image has none), so `corepack
    # enable` would fail on the current LTS.
    ci = (render(stacks=["fastapi", "nextjs"]) / ".github/workflows/ci.yml").read_text()
    assert "corepack" not in ci.lower().replace("corepack no longer ships", "")
    steps = workflows(render(stacks=["fastapi", "nextjs"]))["ci.yml"]["jobs"]
    [step] = [s for job in steps.values() for s in job["steps"] if s.get("name") == "Install pnpm"]
    assert step["uses"].startswith("pnpm/action-setup@")
    assert step["with"] == {"package_json_file": "frontend/package.json"}


def test_no_pnpm_step_without_nextjs(render):
    ci = (render(stacks=["fastapi"]) / ".github/workflows/ci.yml").read_text()
    assert "pnpm" not in ci


def update_steps(project: Path) -> dict[str, dict]:
    return {s["name"]: s for s in workflows(project)["template-update.yml"]["jobs"]["update"]["steps"]}


def test_template_update_names_failed_layers_and_points_to_the_manual_route(render):
    # A failing layer must not stop the others (issue 34): the PR and the issue say which layers failed
    # and name `copier recopy`, which is manual only because it discards local edits.
    steps = update_steps(render())
    assert "failed=" in steps["Apply new template versions"]["run"]
    for name in ("Open the pull request", "Report the update without a token"):
        assert "FAILED" in steps[name]["env"], name
        assert "copier recopy" in steps[name]["run"], name
        assert "overwrites your edits to any file it renders" in steps[name]["run"], name
        assert "git diff" in steps[name]["run"], name
    assert "never run automatically" in steps["Open the pull request"]["run"]


def test_template_update_ends_red_after_a_layer_failed(render):
    final = list(update_steps(render()).values())[-1]
    # !cancelled() so the summary is also written when the PR or issue step fails
    # (https://docs.github.com/en/actions/reference/workflows-and-actions/expressions, status check functions).
    assert final["if"] == "${{ !cancelled() && steps.update.outputs.failed != '' }}"
    assert "exit 1" in final["run"]
    assert "GITHUB_STEP_SUMMARY" in final["run"]


def make_fake_uvx(bin_dir: Path) -> None:
    """A stand-in for `uvx copier==X ...`: every layer has an update; layers named in $FAIL leave a half-done change."""
    bin_dir.mkdir()
    fake = bin_dir / "uvx"
    fake.write_text("""#!/usr/bin/env bash
answers="${@: -1}"
layer="${answers#.copier-answers.}"
layer="${layer%.yml}"
case "$2" in
  check-update) exit 2 ;;
  update)
    # Copier refuses to update a dirty working tree. This is from memory of Copier's code (the docs
    # only advise starting from a clean `git status`), so it is an assumption, not a documented rule.
    if [ -n "$(git status --porcelain)" ]; then echo "dirty tree" >&2; exit 1; fi
    echo "update from $layer" > "changed-by-$layer.txt"
    if [[ " $FAIL " == *" $layer "* ]]; then
      if [[ " $COMMIT_PARTWAY " == *" $layer "* ]]; then  # e.g. a template task that commits
        git add -A && git -c user.name=t -c user.email=t@t commit -qm "partway $layer"
      fi
      echo partial >> README.md
      echo partial > partial-untracked.txt
      exit 1
    fi ;;
esac
""")
    fake.chmod(0o755)


def run_update_step(render, tmp_path: Path, layers: list[str], failing: set[str], partway: set[str] = frozenset()):
    """Run the rendered 'Apply new template versions' script in a throwaway repository."""
    make_fake_uvx(tmp_path / "bin")
    script = update_steps(render())["Apply new template versions"]["run"]
    repo = tmp_path / "scratch"
    repo.mkdir()
    for layer in layers:
        (repo / f".copier-answers.{layer}.yml").write_text(f"_src_path: {layer}\n")
    (repo / "README.md").write_text("start\n")
    env = {"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(tmp_path),
           "COPIER_VERSION": "9.19.1", "GITHUB_OUTPUT": str(tmp_path / "out.txt"),
           "FAIL": " ".join(sorted(failing)), "COMMIT_PARTWAY": " ".join(sorted(partway))}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"], cwd=repo, check=True)
    result = subprocess.run(["bash", "-e", "-c", script], cwd=repo, env=env, capture_output=True, text=True)
    outputs = dict(ln.split("=", 1) for ln in (tmp_path / "out.txt").read_text().splitlines())
    log = subprocess.run(["git", "log", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout.splitlines()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    return result, outputs, log, status, repo


def test_update_script_keeps_the_earlier_layer_when_a_later_one_fails(render, tmp_path):
    result, outputs, log, status, repo = run_update_step(render, tmp_path, ["base", "fastapi"], {"fastapi"})
    assert result.returncode == 0, result.stderr  # the job turns red in a later step, after the PR opens
    assert outputs["updated"].split() == [".copier-answers.base.yml"]
    assert outputs["failed"].split() == [".copier-answers.fastapi.yml"]
    # The subject keeps ".yml" because the workflow's existing subject does (tracked separately).
    # The subject keeps ".yml" because the workflow's existing subject does (tracked separately).
    assert log[0] == "chore: update base.yml template layer"  # the committed base update survives
    assert (repo / "changed-by-base.txt").exists()  # committed by the base layer
    assert status == "", status  # the failed layer's half-done changes are gone
    assert (repo / "README.md").read_text() == "start\n"
    assert not (repo / "partial-untracked.txt").exists()


def test_update_script_when_every_layer_fails_reports_no_update(render, tmp_path):
    result, outputs, log, status, _ = run_update_step(render, tmp_path, ["base", "fastapi"], {"base", "fastapi"})
    assert result.returncode == 0, result.stderr
    assert outputs["updated"] == ""
    assert sorted(outputs["failed"].split()) == [".copier-answers.base.yml", ".copier-answers.fastapi.yml"]
    assert log == ["start"] and status == ""


def test_update_script_with_one_answers_file_and_no_failure(render, tmp_path):
    result, outputs, log, _, _ = run_update_step(render, tmp_path, ["base"], set())
    assert result.returncode == 0, result.stderr
    assert outputs["updated"].split() == [".copier-answers.base.yml"]
    assert outputs["failed"] == ""
    assert log[0] == "chore: update base.yml template layer"


def test_update_script_rolls_back_a_layer_that_committed_partway(render, tmp_path):
    result, outputs, log, status, repo = run_update_step(render, tmp_path, ["base", "fastapi"], {"fastapi"},
                                                         partway={"fastapi"})
    assert result.returncode == 0, result.stderr
    assert "partway fastapi" not in log
    assert log[0] == "chore: update base.yml template layer"
    assert not (repo / "changed-by-fastapi.txt").exists()
    assert status == ""


def test_update_script_continues_to_a_later_layer_after_the_first_fails(render, tmp_path):
    result, outputs, log, status, repo = run_update_step(render, tmp_path, ["base", "fastapi"], {"base"})
    assert result.returncode == 0, result.stderr
    assert outputs["updated"].split() == [".copier-answers.fastapi.yml"]
    assert outputs["failed"].split() == [".copier-answers.base.yml"]
    assert status == ""  # a leftover from base would make the fake (like Copier) refuse fastapi
    committed = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=repo,
                               capture_output=True, text=True).stdout.split()
    assert committed == ["changed-by-fastapi.txt"]  # nothing from the failed base layer
    assert not (repo / "partial-untracked.txt").exists()
