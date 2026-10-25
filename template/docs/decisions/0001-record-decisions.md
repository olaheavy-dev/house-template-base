# 0001. Record decisions in this folder

Status: Accepted

## Context

Choices that are hard to reverse (stack, hosting, data model, security model) get lost in chat and pull requests, and a later contributor or agent can't tell why things are the way they are.

## Decision

Each hard-to-reverse decision gets a short record here, numbered in order, with these sections: Context, Decision, Consequences, Alternatives considered and Sources. Easily reversible choices get one line in the register in `README.md`. An accepted record isn't rewritten: a new record supersedes it, and the old one is marked `Superseded by NNNN`.

## Consequences

Agents read the records before changing anything they cover (`AGENTS.md`), and `.claude/rules/decisions.md` keeps the format consistent.

## Alternatives considered

- Decisions in the wiki or in issues only: not versioned with the code, and invisible to agents.

## Sources

- Michael Nygard, "Documenting architecture decisions": https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions
