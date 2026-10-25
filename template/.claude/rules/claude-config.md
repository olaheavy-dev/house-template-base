---
paths:
  - ".claude/**"
  - "AGENTS.md"
  - "CLAUDE.md"
---

# Agent configuration

Sources: https://code.claude.com/docs/en/settings.md, https://code.claude.com/docs/en/hooks.md, https://code.claude.com/docs/en/memory.md

- `AGENTS.md` is the rulebook; `CLAUDE.md` only imports it (`@AGENTS.md`). Don't turn `CLAUDE.md` into a symlink: Claude Code can't edit through one.
- Permission rules in `.claude/settings.json` are convenience, not a security boundary: they match commands as written. Anything that must never happen is enforced by a hook in `.claude/hooks/` with a test in the template repository.
- Hooks are small Python scripts that read the event JSON on stdin and print a documented decision; they never call the network and finish within their timeout.
- Personal overrides go in `.claude/settings.local.json` (git-ignored), never in the shared file.
- Changes to `.claude/settings.json` and `.claude/hooks/` are owner-only (AGENTS.md, "When merging").
