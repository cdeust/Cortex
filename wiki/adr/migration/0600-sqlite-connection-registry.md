---
kind: adr
number: 0600
title: Preserve sqlite_connection_registry design decisions
status: accepted
---

# ADR-0600: sqlite_connection_registry design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/sqlite_connection_registry.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
SQLite defines transaction isolation at the connection boundary.  The MCP
server executes synchronous handlers on worker threads, so each execution
thread must own the connection whose commit or rollback ends its transaction.
The handler scope then rolls back unfinished work before a worker is reused.

````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
