---
description: "MCP tool catalogue (tiers, purpose, target latency) + slash commands + data flow — extracted from CLAUDE.md (issue #114)."
---

# MCP Tools

51 standalone tools register unconditionally; 3 more register only when an
upstream MCP server is configured (54 total with both present).

```
# source: tests_py/test_main.py::test_standalone_baseline_is_51_tools
#   verified 2026-07-12 by a live DB-less `tools/list` stdio round-trip
#   against `bare-container-contract` + `wiki_migrate`, commit 4be298a3;
#   bumped to 51 by `check_setup` (issue #115).
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
| `recall` | Retrieve memories via 6-signal WRRF fusion | <200ms |
| `consolidate` | Run maintenance: decay, compression, CLS, sleep compute | <5s |
| `checkpoint` | Save/restore working state for hippocampal replay | <100ms |
| `narrative` | Generate project narrative from stored memories | <500ms |
| `memory_stats` | Memory system diagnostics | <50ms |
| `import_sessions` | Import conversation history into memory store | varies |
| `forget` | Hard/soft delete with is_protected guard | <50ms |
| `validate_memory` | Validate memories against filesystem state | <500ms |
| `rate_memory` | Useful/not-useful feedback → metamemory confidence | <50ms |
| `seed_project` | 5-stage codebase bootstrap | varies |
| `anchor` | Mark memory as compaction-resistant (heat=1.0) | <50ms |
| `backfill_memories` | Auto-import prior Claude Code conversations | varies |
| `unified_search` | Unified retrieval across memories, wiki, and code graph | <200ms |
| `get_telemetry` | Retrieval and memory-system telemetry metrics | <50ms |
| `check_setup` | Verify local install (Python, PG driver, DATABASE_URL, connection, extensions, FS) — facade over `mcp_server.doctor` | <500ms |

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

## Tier 3 — Automation & Intelligence (9 tools)

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

## Tier 4 — Wiki (10 tools)

| Tool | Purpose | Target Latency |
|---|---|---|
| `wiki_write` | Create a first-class wiki page (ADR, spec, note) | <100ms |
| `wiki_read` | Read a wiki page | <50ms |
| `wiki_list` | List wiki pages by scope/kind | <50ms |
| `wiki_link` | Create a typed link between wiki pages | <50ms |
| `wiki_adr` | Create an Architecture Decision Record | <100ms |
| `wiki_rename` | Rename a wiki page and update backlinks | <100ms |
| `wiki_verify` | Verify wiki page integrity and links | <100ms |
| `wiki_reindex` | Reindex wiki pages into memory pointers | varies |
| `wiki_purge` | Permanently delete a wiki page | <50ms |
| `wiki_migrate` | Reconcile wiki.pages against FS (backfill + ghost purge) | varies |

## Upstream-integration tools (3, conditionally registered)

These register only when their upstream MCP server is configured, bringing
the total to 54: `ingest_codebase` + `change_impact` (automatised-pipeline)
and `ingest_prd` (prd-spec-generator). With no upstream present, exactly the
**51 standalone tools** above register. Driving the ai-architect pipeline
end-to-end (formerly `run_pipeline`) is **not** part of this server — it
lives in the automatised-pipeline MCP.

## Slash Commands

Discovered from `commands/*.md` at the repo root (not `.claude/commands/` —
this is a plugin repo, so the plugin loader picks these up directly). Each
command is a single Markdown file with a `name`/`description` frontmatter
pair; `/preflight` additionally scopes `allowed-tools` to keep itself
read-only.

| Command | What it does | Roles |
|---|---|---|
| `/methodology` | Retrieves the cognitive methodology profile (via `query_methodology`) for the current working directory and offers `rebuild_profiles` / `list_domains` / `get_methodology_graph` follow-ups | Any user, any session — the general entry point into a domain's profile |
| `/why` | Deterministic blame-path: resolves `⟦rcpt:id⟧` presence-in-context markers via the `why` tool, reports which memories were in context (never that they *caused* an answer — Pearl-rung-1 evidence only) | Anyone auditing why an answer looked the way it did |
| `/preflight [symptôme]` | Runs `python -m mcp_server.doctor` (7 checks) and turns the output into a dependency-ordered, copy-paste repair plan; takes an optional symptom argument to prioritize the relevant check first. Read-only — modifies no files | New users whose install doesn't work yet; support; first-deploy DevOps (issue #119) |

**Convention for adding a new command:** one new `.md` file under
`commands/` (frontmatter: `name`, `description`, and `allowed-tools` if the
command should run with restricted permissions) **plus** one new row in the
table above — the catalogue and the command ship in the same commit.

## Data Flow

### Memory Write Path

1. **Gate**: 4-signal novelty filter (embedding distance, entity overlap, temporal proximity, structural similarity). Decision/error content bypasses the gate — detection is language-aware (see `docs/data-flow.md` § Write Gate Bypass); `force=true` or an `important`/`critical` tag always bypasses, in any language
2. **Curate**: Active curation — merge with similar, link to related, or create new
3. **Store**: PostgreSQL + pgvector with auto tsvector indexing → entity extraction → knowledge graph

### Memory Read Path

1. **Route**: Intent classification (temporal/causal/semantic/entity/knowledge_update/multi_hop)
2. **Enrich**: Doc2Query expansion + concept synonyms
3. **Fuse**: PL/pgSQL `recall_memories()` — WRRF fusion of vector + FTS + trigram + heat + recency (server-side)
4. **Rerank**: FlashRank cross-encoder (client-side, top-3x candidates)
5. **Filter**: Neuro-symbolic rules → ranked results

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
