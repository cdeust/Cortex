# ADR-0445: mcp_server/handlers/seed_project.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/seed_project.py`; original SHA-256 `6a09efe88f0e7eb2bd60cc34ab9fa89ea63b838c4846a7797a077bf0f849723b`.

## Original comment, lines 118–120

````text
# Domain auto-detection: schema documents this behavior; the previous
    # implementation passed an empty string through, which broke the
    # per-domain purge contract (issue #16).
````

## Original comment, lines 185–192

````text
# 2026-05-17 (user feedback): refuse to seed transient roots —
    # ``.claude/worktrees/agent-*``, pytest temp fixtures
    # (``/private/var/folders/.../pytest-of-*``), and other ephemeral
    # paths. Seeding them produced wiki pages titled
    # ``Spec: Entry point: .claude/worktrees/agent-a0ceb782/...`` and
    # ``Spec: Project structure: repo-a`` from fixture runs — both
    # noise that lives forever in the wiki because the underlying path
    # is gone by the next test run.
````

## Original comment, lines 202–204

````text
# Scope purge to this domain (issue #16): seeding repo-A must not
        # wipe out repo-B's seeded memories. Domain authority ends at the
        # project boundary; cross-domain effects are an externality.
````

