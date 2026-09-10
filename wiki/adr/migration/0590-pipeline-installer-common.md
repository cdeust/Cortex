---
kind: adr
number: 0590
title: Preserve pipeline_installer_common design decisions
status: accepted
---

# ADR-0590: pipeline_installer_common design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pipeline_installer_common.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### comment, original line 52

````text
# ignore_errors=True already swallows per-entry failures; this
        # guards path-level errors (e.g. unstatable mount) the flag misses.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
