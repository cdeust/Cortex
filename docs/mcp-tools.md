---
description: "MCP tool catalogue (tiers, purpose, target latency) + slash commands + data flow — extracted from CLAUDE.md (issue #114)."
---

# MCP Tools

57 standalone tools register unconditionally; 3 more register only when an
upstream MCP server is configured (60 total with both present).

```
# source: tests_py/test_main.py::test_standalone_baseline_is_57_tools
#   verified 2026-07-12 by a live DB-less `tools/list` stdio round-trip
#   against `bare-container-contract` + `wiki_migrate`, commit 4be298a3;
#   bumped to 51 by `check_setup` (issue #115), to 52 by `ingest_document`
#   (offline .docx / Confluence export ingest, issue #192), to 54 by
#   `wiki_get_draft` + `wiki_refine_draft` (Path B, ADR-1066, issue #579),
#   to 57 by `predict` + `resolve_prediction` + `calibration` (prediction
#   records and their Brier score, ADR-1076, issue #597).
```

## Tier 1 — Core Memory & Profiling (22 tools)

| Tool | Purpose | Target Latency |
|---|---|---|
| `query_methodology` | Returns cognitive profile + hot memories for current domain | <50ms |
| `detect_domain` | Lightweight domain classification | <20ms |
| `rebuild_profiles` | Full rescan of session data | <10s |
| `list_domains` | Overview of all domains | <10ms |
| `record_session_end` | Incremental profile update + session critique | <200ms |
| `explore_features` | Interpretability exploration (features, attribution, persona, crosscoder) | <100ms |
| `remember` | Store a memory through the 4-signal predictive coding gate | <100ms |
| `recall` | Retrieve memories: 5-signal server-side fusion, post-fusion reranks, FlashRank | <200ms |
| `consolidate` | Run maintenance: decay, compression, CLS, sleep compute | <5s |
| `checkpoint` | Save/restore working state for hippocampal replay | <100ms |
| `narrative` | Generate project narrative from stored memories | <500ms |
| `memory_stats` | Memory system diagnostics | <50ms |
| `import_sessions` | Import conversation history into memory store | varies |
| `forget` | Hard/soft delete with is_protected guard; hard delete is cross-substrate (row + derived wiki claims + unreferenced raw artifact) | <50ms |
| `validate_memory` | Validate memories against filesystem state | <500ms |
| `rate_memory` | Useful/not-useful feedback → metamemory confidence | <50ms |
| `seed_project` | 5-stage codebase bootstrap | varies |
| `anchor` | Mark memory as compaction-resistant (heat=1.0) | <50ms |
| `backfill_memories` | Auto-import prior Claude Code conversations | varies |
| `unified_search` | Unified retrieval across memories, wiki, and code graph | <200ms |
| `get_telemetry` | Retrieval and memory-system telemetry metrics | <50ms |
| `check_setup` | Verify local install, backend-aware (SQLite: store open + FS; PostgreSQL: PG driver, DATABASE_URL, connection, extensions, FS) — facade over `mcp_server.doctor` | <500ms |

### Project decision retrieval

Pass an absolute `project_root` to select that checkout's `wiki/manifest.json`.
`recall` and `unified_search` resolve a canonical `ADR-NNNN` query directly;
`exact_id: true` explicitly requires this form. Missing or stale IDs return an
error instead of unrelated semantic results. Run `wiki_reindex` with the same
project root after checking out or editing decision pages.

Project-scoped `unified_search` also searches wiki text for ordinary queries.
`wiki_read`, `wiki_write` and `wiki_adr` accept the same project root. Project
writes affect checkout files only. Edit canonical `wiki/` pages, then regenerate
the read-only `docs/adr/` mirrors with `wiki_reindex` or
`python scripts/check_project_wiki.py --write`. CI rejects mirror drift.
Omitting `project_root` retains the global wiki scope.

## Tier 2 — Navigation & Exploration (7 tools)

| Tool | Purpose | Target Latency |
|---|---|---|
| `recall_hierarchical` | Fractal L0/L1/L2 weighted recall | <200ms |
| `drill_down` | Navigate into fractal cluster (L2 → L1 → memories) | <100ms |
| `navigate_memory` | Successor Representation co-access BFS traversal | <200ms |
| `get_causal_chain` | Trace entity relationships through knowledge graph | <200ms |
| `detect_gaps` | Identify isolated entities, sparse domains, temporal drift | <500ms |
| `recall_skills` | Recall learned procedural skills by situation | <200ms |
| `why` | Resolve ⟦rcpt:id⟧ injection receipts into presence-in-context evidence (blame path, decision 4255039) | <100ms |

## Tier 3 — Automation & Intelligence (16 tools)

| Tool | Purpose | Target Latency |
|---|---|---|
| `sync_instructions` | Push top memory insights into CLAUDE.md | <500ms |
| `create_trigger` | Prospective memory triggers (keyword/time/file/domain) | <100ms |
| `add_rule` | Add neuro-symbolic hard/soft/tag rules | <100ms |
| `get_rules` | List active rules by scope/type | <50ms |
| `get_project_story` | Period-based autobiographical narrative | <500ms |
| `assess_coverage` | Knowledge coverage score (0-100) + recommendations | <500ms |
| `codebase_analyze` | Native AST codebase analysis (tree-sitter, 7 languages) | varies |
| `curate_wiki` | Auto-curate wiki pages from memory clusters | varies |
| `curate_distill` | Return understanding-level distillation dossiers (error->success, co-access, entity family) for the LLM to author `lesson` memories from (M-D8) | ~200-500ms |
| `ingest_document` | Ingest a .docx or Confluence storage-format XHTML export into the memory/wiki store, with provenance + idempotent re-ingest (issue #192). File-based, no upstream needed | varies |
| `predict` | Record a falsifiable prediction with the confidence held before its outcome is known | <50ms |
| `resolve_prediction` | Settle an open prediction against an observation, naming the evidence that decided it | <50ms |
| `calibration` | Brier score and reliability bands over the resolved predictions | <100ms |
| `ingest_findings` | Ingest an ai-architect findings run off disk: a verified finding becomes a wiki page with receipt memos, a non-verified one a low-confidence hypothesis memory (ADR-0410) | varies |
| `lesson_promotion` | Promote recurring lessons out of episodic memory (M-D6) | <500ms |
| `get_grooming_health` | Grooming backlog counts and staleness ages per judgment-level kind (INC G-4) | ~1s |

## Tier 4 — Wiki (12 tools)

| Tool | Purpose | Target Latency |
|---|---|---|
| `wiki_write` | Create a first-class wiki page (ADR, spec, note) | <100ms |
| `wiki_read` | Read a wiki page | <50ms |
| `wiki_list` | List wiki pages by scope/kind | <50ms |
| `wiki_link` | Create a typed link between wiki pages | <50ms |
| `wiki_adr` | Create an Architecture Decision Record | <100ms |
| `wiki_rename` | Rename a wiki page and update backlinks | <100ms |
| `wiki_verify` | Verify wiki page integrity and links | <100ms |
| `wiki_reindex` | Rebuild wiki contents and exact-ID indexes; explicit project mode also regenerates ADR mirrors | varies |
| `wiki_purge` | Permanently delete a wiki page | <50ms |
| `wiki_migrate` | Reconcile wiki.pages against FS (backfill + ghost purge) | varies |
| `wiki_get_draft` | Fetch a pending draft with its source claims and kind contract, or list pending drafts (Path B) | <50ms |
| `wiki_refine_draft` | Submit refined prose for a draft; records an audit memo, leaves its confidence as the claims set it (Path B) | <100ms |

## Upstream-integration tools (3, conditionally registered)

These register only when their upstream MCP server is configured, bringing
the total to 60: `ingest_codebase` + `change_impact` (ai-architect-mcp-codebase)
and `ingest_prd` (ai-architect-mcp-spec). With no upstream present, exactly the
**57 standalone tools** above register. Driving the ai-architect pipeline
end-to-end (formerly `run_pipeline`) is **not** part of this server — it
lives in the ai-architect-mcp-codebase MCP.

## Slash Commands

Discovered from `commands/*.md` at the repo root (not `.claude/commands/` —
this is a plugin repo, so the plugin loader picks these up directly). Each
command is a single Markdown file with a `name`/`description` frontmatter
pair; `/preflight` additionally scopes `allowed-tools` to keep itself
read-only.

| Command | What it does | Roles |
|---|---|---|
| `/methodology` | Retrieves the cognitive methodology profile (via `query_methodology`) for the current working directory and offers `rebuild_profiles` / `list_domains` follow-ups, plus hypermnesia-mcp-viz's `get_methodology_graph` when that companion MCP is installed | Any user, any session — the general entry point into a domain's profile |
| `/why` | Deterministic blame-path: resolves `⟦rcpt:id⟧` presence-in-context markers via the `why` tool, reports which memories were in context (never that they *caused* an answer — Pearl-rung-1 evidence only) | Anyone auditing why an answer looked the way it did |
| `/preflight [symptôme]` | Runs `python -m mcp_server.doctor` (backend-aware check list) and turns the output into a dependency-ordered, copy-paste repair plan; takes an optional symptom argument to prioritize the relevant check first. Read-only — modifies no files | New users whose install doesn't work yet; support; first-deploy DevOps (issue #119) |

**Convention for adding a new command:** one new `.md` file under
`commands/` (frontmatter: `name`, `description`, and `allowed-tools` if the
command should run with restricted permissions) **plus** one new row in the
table above — the catalogue and the command ship in the same commit.

## Data Flow

### Memory Write Path

1. **Gate**: 4-signal novelty filter (embedding distance, entity overlap, temporal proximity, structural similarity). The content-derived bypasses are granted by an allowlist of origins (`deliberate`, `local_action` — issue #365), so fetched text cannot skip the gate by looking like a decision or an error, and neither can content from a channel nobody has classified; `force` and a `deliberate` write class still bypass at any origin. Decision/error content bypasses the gate — detection is language-aware (see `docs/data-flow.md` § Write Gate Bypass); `force=true` or an `important`/`critical` tag always bypasses, in any language
2. **Curate**: Active curation — merge with similar, link to related, or create new
3. **Store**: PostgreSQL + pgvector with auto tsvector indexing → entity extraction → knowledge graph

### Memory Read Path

1. **Route**: Intent classification (temporal/causal/semantic/entity/knowledge_update/multi_hop)
2. **Enrich**: Doc2Query expansion + concept synonyms
3. **Fuse**: PL/pgSQL `recall_memories()` fuses vector, FTS (`ts_rank_cd`), trigram, heat and recency server-side as a weighted sum of max-normalised scores. The SQLite backend fuses vector, FTS5, heat and recency by rank, w/(k + rank), with no trigram signal
4. **Recollect**: Hopfield completion, HDC, optional spreading activation, dendritic, emotional and mood reranks, reconsolidation, each blended by RRF k = 60
5. **Rerank**: FlashRank cross-encoder (client-side, top-3x candidates)
6. **Filter**: Neuro-symbolic rules → ranked results

### Cognitive Profile Pipeline

1. **Scan**: Read ~/.claude/projects/ for JSONL conversations and memory .md files
2. **Group**: Map projects to domains via project ID matching
3. **Extract**: Per-domain pattern extraction (clustering, n-grams, tool stats, session shape)
4. **Classify**: Felder-Silverman cognitive style from behavioral signals
5. **Bridge**: Cross-domain connections from brain-index cross-refs and text analogies
6. **Detect gaps**: Blind spots by comparing domain coverage against global averages
7. **Learn features**: Sparse dictionary learning on 27D behavioral activation space
8. **Encode**: Per-domain sparse feature activations + persona vectors
9. **Crosscode**: Detect persistent behavioral features across domains
10. **Store**: Persist as ~/.claude/methodology/profiles.json
