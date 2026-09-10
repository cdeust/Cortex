---
kind: adr
number: 0533
title: Preserve mcp_client_pool design decisions
status: accepted
---

# ADR-0533: mcp_client_pool design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/mcp_client_pool.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Singleton connection pool for MCP clients — lazy connect, reuse, idle timeout.
````

### _evict_lru_idle, original line 62

````text
    Pre-condition: the pool is at capacity and a new server is requested.
    Post-condition: returns True and removes exactly one connection (the
    LRU among connections with no in-flight request) if such a connection
    exists; returns False and mutates nothing if every live connection is
    busy. A busy connection is never evicted — closing it would cancel an
    in-flight request (see MCPClient.busy). Iteration order is insertion
    order, so the first non-busy key found is the LRU idle one.
    
````

### _admit_new_connection, original line 82

````text
    Pre-condition: ``server_name`` is not already a live pooled connection.
    Post-condition: the pool holds < max connections (room for one more),
    OR an McpConnectionError is raised. When at capacity, the LRU idle
    connection is evicted; if all are busy, fail fast rather than grow
    unbounded — this is the explicit anti-leak guarantee from the
    pool-leak fix follow-on. source: docs/provenance/bounded-io-plan.md Phase 3.
    
````

### get_client, original line 105

````text
    Pool size is bounded by mcp_pool_max_connections: a cache hit touches
    the LRU ordering; a miss admits via _admit_new_connection (LRU-evict or
    fail-fast) before spawning a child, so the pool never grows unbounded.
    
````

### comment, original line 22

````text
# Insertion-ordered: dict preserves insertion order (PEP 468 / CPython 3.7+),
# so the FIRST key is the least-recently-used connection. ``get_client``
# re-inserts on every cache hit to keep this ordering an LRU ordering.
````

### comment, original line 127

````text
# Upstream MCP servers ship binaries that are not in the default
    # allowlist. Mirror the extension that ap_bridge.py applies on its
    # bridge path so the pool path is not silently rejected. Without
    # this, ingest_codebase fails with "Command not in allowed list"
    # even when mcp-connections.json correctly points at the binary.
    # source: ap_bridge.py L226-L233 — same set, same reason.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
