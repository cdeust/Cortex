---
kind: adr
number: 0585
title: Preserve pipeline_graph_ttl design decisions
status: accepted
---

# ADR-0585: pipeline_graph_ttl design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pipeline_graph_ttl.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Stale graphs trigger a background re-analysis on the next SessionStart
so the following session has a fresh graph — without blocking the
current session.
````

### module, original line 1

````text
Source: user directive "codebase analysis feeding the memory and wiki"
— runs automatically, off the hot path.

````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
