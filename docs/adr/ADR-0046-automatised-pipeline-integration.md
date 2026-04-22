# ADR-0046: Integration with the `automatised-pipeline` plugin

## Status

Proposed

## Context

Cortex's workflow graph currently models what Claude *did* in a project:
which files were touched by which tools, which sessions ran which skills,
which memories were formed. File nodes are the atom — we know a file was
edited, but nothing about its internal structure.

The sister plugin
[`automatised-pipeline`](https://github.com/cdeust/automatised-pipeline)
(AP) is a Rust MCP server that produces a property graph of **code
structure**: tree-sitter AST → LadybugDB graph → Louvain communities →
BM25 + TF-IDF + RRF search. It exposes 23 MCP tools covering indexing,
cross-file resolution (with optional LSP), community detection, impact
analysis, ranked code search, and git-diff change detection for Rust,
Python, and TypeScript.

The two plugins are complementary:

| Axis | Cortex | automatised-pipeline |
|---|---|---|
| Primary unit | session + file + memory | symbol + call + import |
| Timescale | minutes → weeks (consolidation) | static snapshot (re-index on change) |
| Storage | PostgreSQL + pgvector | LadybugDB |
| Retrieval | neural WRRF + rerank | BM25 + TF-IDF + RRF |
| Visualisation | 5-layer workflow graph + wiki | (none — consumed by host) |
| Query language | intent classification | Cypher over the graph |

Fusing them lets the workflow graph descend below the file level and
lets the wiki ground every claim in the code AST.

## Decision

Consume `automatised-pipeline` as a sibling MCP server. Cortex drives
when the pipeline runs; the AST graph is pulled back over MCP and
projected into the workflow graph and the wiki verification pipeline.

Integration surface (four phases, smallest first):

### Phase 1 — AST-aware workflow graph

* New MCP client in `mcp_server/infrastructure/ap_bridge.py` wraps the
  AP tool namespace (`index_codebase`, `query_graph`, `resolve_graph`,
  `cluster_graph`, `search_codebase`, `get_context`, `get_impact`,
  `detect_changes`).
* `mcp_server/infrastructure/workflow_graph_source_ast.py` — peer of
  `_pg` and `_jsonl`. Loads AP graph nodes + edges, constrained to the
  file set Cortex already knows about (join on absolute path).
* Schema additions in `mcp_server/core/workflow_graph_schema_enums.py`:
  * `NodeKind.SYMBOL` with `symbol_type ∈ {function, class, module,
    import}` carried on the node body.
  * `EdgeKind.CALLS` — call site → callee symbol.
  * `EdgeKind.IMPORTS` — file → imported symbol.
  * `EdgeKind.DEFINED_IN` — symbol → file (structural, replaces
    implicit "contained-in" with explicit).
  * `EdgeKind.MEMBER_OF` — function → class.
* Layout (`ui/unified/js/workflow_graph.js`): symbols appear as a **6th
  ring** *inside* each file node, at `r = FILE_R + 40`. Calls between
  symbols in the same file render as short arcs; cross-file calls
  render as violet threads (reusing the existing `cross-domain`
  styling for structural bridging).
* Panel renderer: a function node shows the AP `get_context` payload
  (signature, call sites, callers, tests that reference it). A file
  node gains a "Members" section listing its classes / exports /
  functions.

### Phase 2 — Wiki verification via the AST

* New handler `mcp_server/handlers/wiki_verify.py` exposes a
  `wiki_verify` MCP tool. It walks a wiki page, extracts every
  backticked identifier and every `file:symbol` reference, calls
  `ap.get_symbol` / `ap.query_graph` on each, and returns a dead-
  reference list.
* The wiki editor gets a **Verify** button next to **Export**. Red
  badges appear on pages with broken references; green on pages where
  every symbol resolves.
* A periodic consolidation stage runs `wiki_verify` across the whole
  wiki; pages with dead references lose their `active` lifecycle pill
  and fall back to `area`.

### Phase 3 — Unified search

* Graph's text search box routes queries through both:
  * `ap.search_codebase` for code-like terms (symbol names, path
    fragments).
  * Cortex's existing `recall` for memory / discussion text.
* Results merge via RRF (both systems already report RRF-compatible
  ranks).
* New MCP tool `cortex:search_unified` exposes the fused ranking to
  other callers (tests, benchmarks, skills).

### Phase 4 — Change-impact annotation

* On every git commit in a watched project, the `post_tool_capture`
  hook (or a new `post_commit` hook) calls `ap.detect_changes`
  followed by `ap.get_impact` on each changed symbol.
* Affected nodes in the workflow graph get a transient "impact" pulse
  (amber halo for 2 minutes of graph render time), with edge weight
  scaled by `get_impact`'s blast-radius score.
* Panel shows the affected-symbol set when the user clicks an edited
  file — "this change reaches 18 nodes across 4 modules".

## Coexistence model

Both plugins install side-by-side:

```
claude plugin install cortex
claude plugin install automatised-pipeline
```

`cortex-setup-project` gains a final step: if `ap` is installed, run
`ap.index_codebase` on each detected project root. Re-indexing after
edits is driven by the `post_tool_capture` hook, debounced per file.

No hard dependency — Cortex functions with or without AP. When AP is
absent, the L3.5 symbol ring and wiki-verify are hidden; the graph
degrades gracefully to its current behaviour.

## Consequences

**Gain.**

* The workflow graph gains true structural depth: you can see not just
  "Cortex touched `auth.py`" but "the `login()` function called
  `verify_token()` in `session.py`". Cross-file call graphs make
  refactor surfaces visible.
* Wiki pages become verifiable. The current wiki says "the retrieval
  path uses WRRF" as free text — post-integration, that sentence is
  linked to the actual `recall_memories()` PL/pgSQL function, and the
  link is audited nightly.
* Search quality jumps. BM25 over a real AST index returns
  symbol-level hits, not substring matches in memory bodies.
* Impact analysis — "what breaks if I change this?" — becomes a
  first-class graph query.

**Lose.**

* Hard dependency window during AP indexing. First `index_codebase`
  on a large repo takes seconds to minutes; we cache per-commit and
  only re-index touched files on subsequent calls.
* Deployment complexity: users must install two plugins. Mitigated by
  making AP optional (graceful degradation).
* LadybugDB is another datastore in the critical path. Sandboxed to
  AP's own process — Cortex never writes there.
* Only Rust / Python / TypeScript are covered by AP at present; other
  languages (Go, Swift, Kotlin, SQL) remain file-level in the graph.

**Neutral.**

* The Cortex schema grows by 1 `NodeKind` and 4 `EdgeKind`. Validator
  rules extend accordingly; existing graphs remain valid (new kinds
  are opt-in per loader).
* Layout algorithm stays the same — symbols slot into the existing
  radial hierarchy as a new ring; no simulator rewrite.

## Implementation order

1. `ADR-0046` committed (this document).
2. `ap_bridge.py` + smoke test that can call `ap.health_check`.
3. Schema enum additions + validator updates.
4. Phase 1 loader + builder wiring + panel rendering + tests.
5. Phase 2 `wiki_verify` tool + UI badge.
6. Phase 3 unified search.
7. Phase 4 impact pulse.

Each phase ships behind a feature flag (`CORTEX_ENABLE_AP=1`) so the
main graph path never regresses while the bridge matures.

## References

* [automatised-pipeline](https://github.com/cdeust/automatised-pipeline)
  — AP's README documents the 23-tool surface and the
  tree-sitter → LadybugDB → Louvain → BM25 pipeline.
* Cortex `WorkflowGraphSource` — current facade the AST loader slots
  into as a peer of `_pg` and `_jsonl`.
* Cortex `validate_graph` — the invariant checker that must learn the
  new edge arities.
