# ADR-0399: mcp_server/handlers/ingest_codebase.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/ingest_codebase.py`; original SHA-256 `5ee6eac2cab26c3cf2ffc07c44d39f816093af5328880947d12c863388c5955d`.

## Original docstring, lines 1–23

````text
"""Handler: ingest_codebase — pull codebase analysis from the upstream
ai-architect-mcp-codebase MCP server into Cortex's store.

Flow
----
1. Resolve the project's graph path (cache hit or upstream analyze).
2. Pull the FULL chain hierarchy from the Kuzu graph via Cypher:
   every Function/Method/Struct, every File, every call edge between
   symbols, every File→symbol containment edge.
3. Project upstream artefacts into Cortex's stores: memories + KG
   entities + KG edges + wiki reference pages per process.
4. Return an ingestion summary.

Cortex is the CONSUMER — upstream owns analysis, Cortex owns
documentation and knowledge-graph state.

This file is the composition root. Implementation is split:
  - ingest_codebase_schema.py    — MCP tool schema
  - ingest_codebase_graph.py     — graph-path resolution + analyze
  - ingest_codebase_cypher.py    — Kuzu fetchers
  - ingest_codebase_writers.py   — MemoryStore writers
  - ingest_codebase_pages.py     — process wiki rendering
"""
````

## Original comment, lines 70–77

````text
# Symbol ingest page size. Symbols are fetched and written in pages of
# this size so the peak RAM stays at O(page_size) rather than O(N_symbols).
# Kuzu queries use SKIP/LIMIT pagination per page so the MCP JSON-RPC
# blob per request is bounded regardless of total corpus size.
# Call edges and containment edges are pulled once after all symbol pages
# complete (they reference qualified_names that must already exist).
# source: Carnot analysis — root cause of OOM is accumulating all symbols
#   in one Python list before any write; adaptive pagination removes that.
````

## Original comment, lines 82–85

````text
# Edge fetch+write page size. Edges are paged out of Kuzu via SKIP/LIMIT and
# written one page at a time to a single staging sink on the loop thread —
# constant memory on both sides. source: benchmark — the proven 1000-row chunk
# (74MB peak RSS / ~49.5k rows/s streaming 500k rows, measured 2026-06-03).
````

## Original comment, lines 224–224

````text
# stride != page_size — see symbol_page_stride (2026-06-11 RCA).
````

## Original docstring, lines 400–407

````text
"""Pull ALL processes via upstream get_processes; respect optional cap.

    Upstream pages its process list by serialized size (``truncated`` +
    ``next_offset``, ai-architect-mcp-codebase ``do_get_processes``); a single
    call returns only the first page. Follow the cursor until exhausted —
    the previous single-shot read silently dropped every process past the
    first byte-budget page (2026-06-11 RCA).
    """
````

## Original docstring, lines 446–452

````text
"""Attach participating symbol qns to each process (in place).

    ``get_processes`` returns only counts (``node_count``); the actual
    membership lives in the graph as ParticipatesIn edges. Pages without
    symbols carry no documentation value (2026-05-17 user feedback), so
    this fetch is what makes the wiki pages worth writing.
    """
````

## Original comment, lines 492–495

````text
# A plugin-cache copy is NOT a project. Indexing them produced 8
    # duplicate symbol universes (versions 3.18.3–3.19.5 of Cortex
    # itself) whose graphs outlived their deleted source dirs and
    # polluted the galaxy + impact queries (user report 2026-06-13).
````

## Original comment, lines 539–541

````text
# The fresh graph supersedes any precedent for this project — remove
    # stale ``<name>-*`` siblings so resolve_graph_paths returns only the
    # current graph (no stale/empty hits in the impact query).
````

## Original comment, lines 605–608

````text
# ── Phase 5: docs content (INC5.3, D6) — optional, cheap relative to
        # the symbol/edge phases above; content indexing of Markdown-family
        # files happens on Cortex's side only (D6 rationale in
        # ingest_docs_content_writers.py's module docstring). ────────────────
````

## Original comment, lines 622–625

````text
# entities_written = rows actually INSERTed by the staging sink
        # (post NOT EXISTS dedup); entities_seen = rows streamed at it.
        # The previous response reported seen counts AS written — a
        # misnomer that masked the domain-blind dedup bug (2026-06-11 RCA).
````

## Reviewed remaining docstring (mcp_server/handlers/ingest_codebase.py, interim lines 113–122)

````text
Remove stale graphs for the SAME project once a fresh one is built.

Graph dirs are keyed ``<project-name>-<hash>`` (project_key) — but a
path move, a version-named legacy dir, or a re-index under a new hash
leaves the old ``<name>-*`` dir behind. Those precedents pollute
``resolve_graph_paths`` (the impact query then scans 4 graphs, some
stale/empty, and can pick a stale hit). Per "update a version → remove
the precedent", drop every sibling sharing this project's name prefix
except the one we just wrote. Returns removed dir names.
````

