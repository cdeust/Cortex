---
kind: adr
number: 0623
title: Preserve viz_client design decisions
status: accepted
---

# ADR-0623: viz_client design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/viz_client.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
This module discovers the live viz instance via the registry file that
``mcp_server/server/viz_instance.py`` writes (``{pid, port,
started_at}`` at ``~/.cache/cortex/viz-server.json`` — the file format
is the contract between the two processes; this is the read side, that
module is the write side) and drains the full graph through the
paginated ``/api/graph/slice`` endpoint. Pages are bounded; the UNION
of pages is complete — never a lossy cap (user direction 2026-06-12).
````

### module, original line 1

````text
The drained graph is memoised per ``phase_seq``: the viz build bumps
the sequence every time it publishes more nodes, so a repeat tool call
against an unchanged graph costs one small ``/api/graph/slice``
header probe instead of a multi-MB drain.

````

### fetch_live_graph, original line 74

````text
    Returns ``{"nodes": [...], "edges": [...], "meta": {"source":
    "live-cache", "phase_seq": int, "full_ready": bool}}`` with FULL
    node/edge records (the slice endpoint serves the cache, not the
    slim wire). Complete: pages are drained until ``done``.
    
````

### comment, original line 31

````text
# One page of the slice drain. Matches the server-side default in
# ``get_graph_slice``; at the measured 143k-node galaxy this drains in
# 8 pages. Bounded per request, complete across requests.
````

### comment, original line 36

````text
# Per-request socket timeout. The slice endpoint serves from the
# in-process cache (no PG work), so multi-second pages indicate a
# GIL-pinned build phase — waiting is correct, hanging forever is not.
````

### comment, original line 104

````text
# A page failed mid-drain: a partial graph silently posing
            # as complete is exactly the failure mode this design
            # forbids — report no live graph and let the caller fall
            # back to the local build.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
