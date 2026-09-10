---
kind: adr
number: 0620
title: Preserve upstream_availability design decisions
status: accepted
---

# ADR-0620: upstream_availability design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/upstream_availability.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Gates the registration of the three upstream-dependent tools
(``ingest_codebase`` + ``change_impact`` → ai-architect-mcp-codebase; ``ingest_prd``
→ prd-spec-generator). On a standalone install with no upstream configured,
these tools do not register — so every advertised tool works out of the box.
````

### module, original line 1

````text
source: Anthropic MCP Directory submission decision 2026-06-19 — the bundle
presents 43 standalone tools; the 3 upstream-integration tools auto-register
only when their upstream MCP server is actually present (mcp-connections.json
entry, marketplace plugin, PATH binary, or sibling checkout).

````

### _server_command_runnable, original line 25

````text
    A path-form command must exist and be executable; a bare command name must
    resolve on PATH. A configured-but-broken entry reads as unavailable so the
    gated tool is not advertised when it could only fail.
    
````

### codebase_upstream_available, original line 45

````text
True when the ai-architect-mcp-codebase (``codebase``) MCP server is reachable.
````

### codebase_upstream_available, original line 45

````text
    Either explicitly wired in mcp-connections.json, or discoverable via the
    marketplace plugin / PATH binary / sibling source checkout.
    
````

### comment, original line 52

````text
# Lazy import: pipeline_discovery is infra-internal and heavier than this
    # module; importing at call time keeps the gate cheap when already wired.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
