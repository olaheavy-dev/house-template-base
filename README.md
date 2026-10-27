# house-template-base

[![Test](https://github.com/olaheavy-dev/house-template-base/actions/workflows/test.yml/badge.svg)](https://github.com/olaheavy-dev/house-template-base/actions/workflows/test.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/olaheavy-dev/house-template-base/badge)](https://scorecard.dev/viewer/?uri=github.com/olaheavy-dev/house-template-base)

The base layer of my project templates: the coding-agent workflow, CI and supply-chain security, repository governance and decision records that every new project starts from. It's a [Copier](https://copier.readthedocs.io/) template, not a package: it copies files into a project once, the project owns them from then on, and `copier update` brings later improvements in as a reviewable merge.

## Layers

Each layer is its own template repository with its own versions, applied with its own answers file (`.copier-answers.<layer>.yml`), so a project takes exactly the layers it needs:

| Layer | Gives a project |
| --- | --- |
| **base** (this repository) | `AGENTS.md` rulebook and Claude Code setup with guardrail hooks (plus a project `.mcp.json` with the Next.js DevTools server, pinned and with telemetry off, for the `nextjs` stack, and the Microsoft Learn docs server for `dotnet`), CI and security workflows, rulesets and settings as code, Dependabot, policy files, decision records |
| `house-template-fastapi` (planned) | FastAPI, PostgreSQL with pgvector, storage, LangChain, LangGraph and LangSmith |
| `house-template-nextjs` (planned) | Next.js shell, design tokens, accessibility and screenshot checks |
| `house-template-dotnet` (in progress) | ASP.NET Core modular monolith, EF Core, Keycloak, mutation testing; a project has one backend, FastAPI or .NET |

Each file has exactly one owning layer (listed in `.github/template-owned/<layer>.txt`), so layers never fight over a file during updates.

## Use it

```bash
copier copy --trust gh:olaheavy-dev/house-template-base my-project
cd my-project && git init -b main && git add -A && git commit -m "chore: start from house-template-base"
make install && make check
make repo-settings   # once the GitHub repository exists: rulesets, security and Actions settings
```

`--trust` is needed because the template runs a post-copy message and, in later versions, migrations. Apply only templates from this organisation.

## What a generated project gets

- **Agents work under enforced rules.** `AGENTS.md` is the rulebook, and `CLAUDE.md` imports it. Hooks enforce what permission rules can't:
  - an allow-list push guard (named branches only, never main, no force);
  - a secrets guard on file reads, writes and Grep globs;
  - a stop hook that runs the quick checks before an agent reports success.
- **Every rule has its check.** Pre-commit runs hygiene, gitleaks, actionlint and zizmor. CI runs `make check`. CodeQL and zizmor findings gate merges through the ruleset.
- **Supply chain:**
  - every action is pinned to a commit SHA, and GitHub's pinning policy is on;
  - dependency review checks licences;
  - a reusable image publisher attaches SLSA provenance and an SBOM, verified before deploy, and passes the commit to the build as `GIT_COMMIT`;
  - OpenSSF Scorecard runs.
- **Improvements flow both ways:**
  - a PR that edits a template-owned file gets a CI warning;
  - the `template-candidate` label carries generic changes upstream;
  - a weekly workflow runs `copier update` and opens a PR when a layer releases a new version.

## How this template is tested

`uv run pytest` renders the template with Copier's API and checks the result. It feeds every hook the event JSON Claude Code sends, lints the rendered workflows with zizmor and actionlint for several stack combinations, and checks that every required status check is a job the workflows run. It also runs `copier update` between two tagged versions and confirms that local edits survive. CI also renders a project and runs that project's own pre-commit checks on `main`.

## Releases

release-please turns Conventional Commit titles into a release PR and, on merge, a `vX.Y.Z` tag. Projects update from those tags. See [`CHANGELOG.md`](CHANGELOG.md).

## Licence

Copyright © 2026 Sunkanmi Olawuwo. All rights reserved. Public for portfolio purposes; see [LICENSE](LICENSE).
