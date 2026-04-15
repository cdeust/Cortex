# ADR-0044 — Upstream MCP ingestion (Cortex is the consumer)

**Status**: accepted
**Date**: 2026-04-15
**Supersedes**: the `run_pipeline` / ai-architect integration (removed).

## Context

Cortex was originally designed as the orchestrator of an external pipeline
(`run_pipeline` drove the ai-architect MCP server end-to-end through 11
stages). Two things have since changed:

1. **ai-architect is dead.** No further development; `run_pipeline` points
   at a server that no longer exists.
2. **Two new upstream servers produce artefacts Cortex's views need.**
   - `ai-automatised-pipeline` — Rust MCP that performs tree-sitter
     parsing, graph construction (LadybugDB), BM25 + vector + RRF search,
     community detection, and process tracing over a codebase.
   - `prd-spec-generator` — TypeScript MCP that authors and validates
     PRDs, exposing pipeline-state tools for structured generation.

Cortex itself is a memory / knowledge / profiling system. It stores
evidence (wiki pages, memories, knowledge-graph entities/edges) and
renders views (Wiki, Board, Knowledge, Graph) on top of that store.

## Decision

Cortex is the **consumer** of these upstream MCP servers, not the driver.
Two new ingest handlers are added, each bridging one upstream server:

- `ingest_codebase(project_path, …)` — calls the codebase server's
  `analyze_codebase` (plus `search_codebase` / `get_processes`),
  materialises the results as Cortex memories + knowledge-graph
  entities/edges + wiki reference pages under `reference/codebase/`.
- `ingest_prd(path | content | pipeline_id, validate?, …)` — fetches a
  PRD document (from disk, inline, or a prd-gen pipeline state), writes
  the PRD as a wiki spec page under `specs/`, and extracts decisions /
  requirements into individually-tagged memories.

The existing `run_pipeline` handler, the `mcp_server/handlers/pipeline/`
sub-package, the corresponding tests, and the `agent_config.py` entry
referencing it have been deleted.

## Consequences

- Upstream owns analysis; Cortex owns documentation + knowledge state.
- After one `ingest_*` call, all subsequent navigation (`recall`,
  `navigate_memory`, `get_causal_chain`, `wiki_read`,
  `get_methodology_graph`, `open_visualization`) operates on Cortex's
  own store — no further upstream round-trips are required to browse
  the views.
- Graph-path memoisation: `ingest_codebase` caches the upstream graph
  path as a protected memory tagged `_code_graph:<project-id>` so
  re-running the tool without `force_reindex=true` skips re-indexing.
- Configuration: users supply upstream server locations in
  `~/.claude/methodology/mcp-connections.json`. Template is shipped at
  `docs/mcp-connections.example.json`.

## Rejected alternatives

- **Drive the upstream pipeline from Cortex.** Conflates responsibilities;
  the pipeline already has its own orchestration layer. Cortex should
  not be the conductor.
- **Expose raw pipeline tools as Cortex tools (passthrough).** Tempting
  for "Graph" view drill-down, but fragile: every upstream change forces
  a Cortex tool-surface change. Instead, ingestion copies the relevant
  slice of upstream output into Cortex's own store, which is the
  long-term source of truth.
- **Merge the two concerns into one `ingest` tool.** Codebase and PRD
  ingestion have different sources, different outputs, and different
  failure modes. One tool each keeps each TDQS schema focused.
