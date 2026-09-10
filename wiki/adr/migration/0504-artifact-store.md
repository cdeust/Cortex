---
kind: adr
number: 0504
title: Preserve artifact_store design decisions
status: accepted
---

# ADR-0504: artifact_store design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/artifact_store.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
When an auto-captured tool output exceeds GIST_BUDGET, the full raw output is
written here and the memory body keeps only a gist + a pointer to the artifact
path (see core/gist_extraction.py and docs/provenance/bounded-io-phase2-design.md F3).
The artifact is a plain Markdown file loadable by the Read tool — zero new MCP
surface, nothing dropped from the corpus.
````

### comment, original line 24

````text
# sha256 hex is 64 chars; the first 16 (64 bits) give a collision-free key for
# the artifact corpus (millions of files → negligible birthday-collision risk)
# while keeping filenames short. Mirrors backfill_helpers.file_hash([:16]).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
