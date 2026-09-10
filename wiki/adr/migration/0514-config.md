---
kind: adr
number: 0514
title: Preserve config design decisions
status: accepted
---

# ADR-0514: config design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/config.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
The root is overridable via ``CORTEX_CLAUDE_DIR``. Every real-data path in
Cortex — the SQLite store, the wiki tree, profiles, the session log —
derives from it, so that single variable is the one seam a test session (or
any sandboxed run) needs in order to bind to a throwaway tree instead of the
operator's real ``~/.claude``.
````

### module, original line 1

````text
source: incident 2026-07-28 (issue #219). Without this seam the test suite
had no way to redirect the wiki root: ``consolidate.handler()`` calls
``write_dashboards(WIKI_ROOT)``, which walked the developer's real wiki
(16,234 files — the reported "suite hangs at 58%") and wrote generated
dashboards into ``~/.claude/methodology/wiki/_dashboards/``. Patching each
derived constant per test is the throw-site fix; the root is here.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
