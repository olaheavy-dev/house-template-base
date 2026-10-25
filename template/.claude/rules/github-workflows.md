---
paths:
  - ".github/**"
---

# GitHub workflows and repository settings

Owned by house-template-base. Sources: GitHub's secure-use reference (https://docs.github.com/en/actions/reference/security/secure-use) and zizmor's audits (https://docs.zizmor.sh/audits/).

- Pin every action to a full commit SHA with the release in a comment (`uses: actions/checkout@<sha> # v7.0.1`). Get the SHA from GitHub (`gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`), never from memory. Dependabot keeps the pins current.
- Top-level `permissions: {}`; grant each job only what it needs, and say why in a comment when it needs write access.
- `actions/checkout` always sets `persist-credentials: false`.
- Every job has `timeout-minutes`. Pull-request workflows use `concurrency` with `cancel-in-progress` for pull requests only; never cancel a release or deploy halfway.
- No `pull_request_target` or `workflow_run` on untrusted code. Pass untrusted values (`github.event.*` titles, bodies, branch names) through `env:`, never inline `${{ }}` in `run:`.
- Docker images in workflows are pinned by digest.
- `make check` runs actionlint and zizmor (pedantic) on every workflow; fix findings rather than silencing them, and explain any `# zizmor: ignore[...]` in the same comment.
- Rulesets live in `.github/rulesets/` and are applied with `make repo-settings`; changing them is owner-only (AGENTS.md, "When merging"). A required check must run on every pull request (no `paths:` filter), or merges wait for it forever.
