# ADR-0400: mcp_server/handlers/ingest_codebase_cypher.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/ingest_codebase_cypher.py`; original SHA-256 `428f14800e9d244947eb1562fa54374213301ef49300ee1650eeadcbb1922d9a`.

## Original docstring, lines 1–22

````text
"""Cypher fetchers for ingest_codebase.

Pure data extraction from the upstream Kuzu graph via the
``query_graph`` MCP tool. No I/O against Cortex's own stores —
that's the writers' job.

Schema (probed 2026-04-25 against ai-architect-mcp-codebase graph):
  - Function/Method/Struct nodes: id, name, qualified_name,
    start_line, end_line, visibility, is_async (Method also has
    receiver_type).
  - File node: id, path, name, extension, size_bytes.
  - Relationships are untyped in this Kuzu schema; we walk via
    label-restricted patterns.

File attribution is **derived from the (:File)-[]->(:symbol)
containment edges**, not from string-splitting qualified_name. The
containment edges are language-agnostic — whatever the upstream
indexer produces for Rust, Python, or TypeScript, the File→symbol
relationships are the source of truth. ``file_path_from_qn`` exists
only as a last-resort fallback when a symbol has no containment
edge in the graph (orphan symbols, virtual symbols).
"""
````

## Original comment, lines 52–53

````text
# source: structural — the call-edge and file-containment queries RETURN
# exactly two columns; shorter rows are malformed and skipped
````

## Original docstring, lines 124–143

````text
"""Run a single cypher query, draining upstream byte-budget pages.

    Upstream ``query_graph`` (ai-architect-mcp-codebase ≥0.4.0,
    ``do_query_graph`` in src/main.rs) bounds every response two ways:
      1. ``LIMIT 500`` is injected into any Cypher lacking a LIMIT clause
         (``limit_injected: true``) — pagination CANNOT recover rows past
         that, so every caller here MUST declare its own LIMIT.
      2. Wide rows are byte-paged: the response carries
         ``truncated: true`` + ``next_offset`` and the caller must re-call
         with ``offset=next_offset`` to drain the remaining rows.
    Ignoring (2) silently truncated ingests (~887/4669 call edges,
    2026-06-11 RCA). This function follows ``next_offset`` until
    ``truncated`` is false and returns the merged result; merged size is
    bounded by the caller's explicit LIMIT.

    Returns (result_dict, error_message). On upstream-reported errors
    (status=error), result is an empty dict and the error_message is
    populated. Transport errors raise; callers catch narrow transport
    classes and surface them as diagnostics.
    """
````

## Original comment, lines 164–165

````text
# Non-advancing cursor would loop forever — upstream contract
            # violation; surface it instead of spinning.
````

## Original docstring, lines 174–182

````text
"""Per-label row count fetched by one ``fetch_symbols_page`` call.

    Callers MUST advance ``offset`` by exactly this stride between calls.
    The previous caller advanced by ``page_size`` while each label's query
    used ``LIMIT page_size // 3`` — every window silently skipped the
    per-label rows between the two (≈2 000 of 3 645 Functions on the
    Cortex graph, 2026-06-11 RCA). Keeping the stride and the LIMIT in
    one function makes that mismatch impossible.
    """
````

## Original comment, lines 376–380

````text
# File-fetch page size. A LIMIT-less Cypher gets `LIMIT 500` injected
# upstream (QUERY_GRAPH_ROW_LIMIT, ai-architect-mcp-codebase src/main.rs), which
# silently capped fetch_files at 500/1233 files (2026-06-11 RCA). Paging with
# an explicit SKIP/LIMIT below that injection threshold keeps each JSON-RPC
# payload bounded AND visits every File node.
````

