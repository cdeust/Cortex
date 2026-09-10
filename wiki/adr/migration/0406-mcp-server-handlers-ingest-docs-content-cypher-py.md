# ADR-0406: mcp_server/handlers/ingest_docs_content_cypher.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/ingest_docs_content_cypher.py`; original SHA-256 `849fd3e3bd889c3ce41aa7827db787cb4a33d0b2d53515be8646f34a6ecf36b7`.

## Original docstring, lines 1–9

````text
"""Cypher fetchers for the ingest_codebase docs-content pass (INC5.3 / D6).

Reads Markdown-family ``File`` nodes and their ``References_File_File``
edges out of the upstream ai-architect-mcp-codebase (AP) graph. Deliberately
independent of ``ingest_codebase_cypher.py`` — its own pagination helper,
own module — so this optional pass (design decision D6: "passe
optionnelle") can be edited, tested, or removed without touching the
symbol/edge Cypher shared with the rest of ``ingest_codebase``.
"""
````

## Original comment, lines 29–33

````text
# ai-architect-mcp-codebase's own Markdown-family extension set.
# source: ai-architect-mcp-codebase/src/indexer/light_link.rs:25,
#   `const MD_EXTS: &[&str] = &["md", "markdown", "mdx"];`
# The docs pass indexes exactly the files AP's light-link post-pass already
# cross-references via References_File_File — no wider, no narrower.
````

## Original comment, lines 36–40

````text
# Page size for both File-node and References_File_File queries.
# source: ai-architect-mcp-codebase injects `LIMIT 500` into any un-LIMITed
# Cypher (QUERY_GRAPH_ROW_LIMIT, src/main.rs — see also
# ingest_codebase_cypher._FILE_PAGE_SIZE, same upstream contract) — every
# query here declares its own SKIP/LIMIT below that injection threshold.
````

## Original comment, lines 43–44

````text
# source: structural — the doc-refs query RETURNs exactly two columns
# (src, dst); shorter rows are malformed and skipped
````

## Original docstring, lines 54–62

````text
"""One Cypher query, following upstream's byte-budget pagination.

    Same contract as ``ingest_codebase_cypher._run_query`` (duplicated
    here rather than imported — see module docstring for why): upstream
    ``query_graph`` paginates wide results via ``truncated``/``next_offset``;
    this loop drains every page before returning. Returns
    ``(result, error_message)``; on upstream-reported error, result is
    ``{}`` and error_message is populated. Transport errors raise.
    """
````

## Original docstring, lines 141–155

````text
"""Pull References_File_File edges whose SOURCE is a known Markdown doc.

    AP's light-link post-pass only ever emits this edge label FROM a
    Markdown file (source: light_link.rs:68-76, "Markdown ... ->
    References_File_File"), to either another doc or a code file it
    describes (carto test case: "docs/guide.md -> mod.py"). Filtering the
    source against ``known_doc_paths`` (the set this run already fetched
    via ``fetch_doc_files``) scopes the query to genuine doc-origin edges;
    the destination is left unfiltered so doc->code references survive —
    ``ingest_docs_content_writers.write_doc_reference_edge`` drops any
    edge whose destination entity was never ingested (dangling endpoint,
    same policy as the containment/call edges in the main ingest phases).
    Deduplicated client-side (a (src, dst) pair appearing on multiple
    Markdown lines collapses to one edge).
    """
````

