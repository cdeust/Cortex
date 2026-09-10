---
kind: adr
number: 0596
title: Preserve scanner_parse design decisions
status: accepted
---

# ADR-0596: scanner_parse design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/scanner_parse.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### build_conversation_record, original line 132

````text
Assemble a conversation record from extracted metadata and stats.
````

### comment, original line 70

````text
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
