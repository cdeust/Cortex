---
kind: adr
number: 0632
title: Preserve workflow_graph_ast_response design decisions
status: accepted
---

# ADR-0632: workflow_graph_ast_response design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/workflow_graph_ast_response.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of ``workflow_graph_source_ast.py`` (issue #275) — shared by
both the symbol-loading and edge-loading concerns, so it gets its own
narrow module rather than living inside either.
````

### normalize_search_hits, original line 76

````text
Normalize a raw AP ``search_codebase`` response into
    ``[{id, qualified_name, file_path, score, snippet, source}, ...]``.
````

### normalize_search_hits, original line 76

````text
    Split out of ``workflow_graph_source_ast.WorkflowGraphASTSource
    .search_codebase`` (over the 300-line file cap) — this module already
    owns "normalize an AP response shape", the same seam. Rows with no
    ``qualified_name`` are dropped; ``id`` is deterministic so RRF fusion
    can dedupe with the same scheme used for SYMBOL graph nodes.
    
````

### build_path_tails, original line 105

````text
    Shared by the symbol- and edge-loading queries (both need to match a
    ``paths`` entry, which may be absolute, against AP's repo-relative
    ``qualified_name``/``File.id`` prefixes — matching by tail lets either
    form work without knowing the other side's root).
````

### build_path_tails, original line 105

````text
    source: measured 2026-06-04 — a blanket ``LIMIT 500`` with no WHERE
    clause returned 0 rows for ``consolidate.py`` because the first 500
    Functions all started with ``benchmarks/*``/``_pipeline/*``; building
    every tail here lets the caller construct a server-side WHERE
    predicate that filters by file prefix instead of discarding in Python.
    
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
