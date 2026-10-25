# Owned by house-template-base. Stack layers don't edit this file: each adds mk/<layer>.mk, which
# appends its targets to INSTALLS, CHECKS and FAST_CHECKS. `make help` lists every target.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-builtin-rules

PRE_COMMIT_VERSION := 4.7.0
COPIER_VERSION := 9.19.1

INSTALLS := install-base
CHECKS := check-base
FAST_CHECKS :=

-include mk/*.mk

.PHONY: help install check check-fast install-base check-base repo-settings template-status

help: ## List every target
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' Makefile $(wildcard mk/*.mk) | sort | awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

install: $(INSTALLS) ## Install toolchains, dependencies and git hooks

check: $(CHECKS) ## Everything CI runs

check-fast: $(FAST_CHECKS) ## Quick checks: run by the pre-push hook and the agent stop hook
	@echo "check-fast: ok"

install-base: ## Install pre-commit and the git hooks
	uv tool install --upgrade "pre-commit==$(PRE_COMMIT_VERSION)"
	pre-commit install

check-base: ## Repository hygiene, secret scan and workflow lint on every file
	@# no-commit-to-branch guards commits, not checks: skip it so make check passes on main (CI)
	SKIP=no-commit-to-branch pre-commit run --all-files

repo-settings: ## Apply rulesets and security settings to the GitHub repository (owner only)
	tools/apply-repo-settings.sh

template-status: ## Show whether each template layer has a newer version
	@for f in .copier-answers.*.yml; do \
		printf "%s: " "$$f"; \
		if uvx "copier==$(COPIER_VERSION)" check-update --quiet --answers-file "$$f"; then echo "up to date"; \
		else status=$$?; if [ $$status -eq 2 ]; then echo "update available"; else echo "check failed ($$status)"; fi; fi; \
	done
