# API Reference — MCP Tool Schemas

This document describes the input schemas, response formats, and error codes for all 34 MCP tools exposed by JARVIS.

## Protocol

- **Transport:** Newline-delimited JSON-RPC 2.0 over stdin/stdout
- **Protocol version:** `2025-11-25` (backwards-compatible with `2024-11-05`)
- **Entry point:** `python -m mcp_server`
- **Framework:** FastMCP 2.0+

---

## Tier 1 — Core Memory & Profiling

### `query_methodology`

Returns the cognitive profile for the current domain, suitable for system prompt injection. Also surfaces hot memories and fired triggers.

**Input Schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `cwd` | string | No | Current working directory for domain detection |
| `project` | string | No | Claude project ID override |
| `first_message` | string | No | First message hint for content-based detection |

**Target Latency:** <50ms

---

### `detect_domain`

Lightweight domain classification without full profile generation.

**Input Schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `cwd` | string | No | Current working directory |
| `project` | string | No | Claude project ID |
| `first_message` | string | No | First message content hint |

**Target Latency:** <20ms

---

### `rebuild_profiles`

Full rescan of session data to rebuild all cognitive profiles.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `domain` | string | No | — | Rebuild only this domain |
| `force` | boolean | No | `false` | Force rebuild even if profiles are fresh (<1hr) |

**Target Latency:** <10s

---

### `list_domains`

Overview of all known domains with summary statistics.

**Input Schema:** *(no parameters)*

**Target Latency:** <10ms

---

### `record_session_end`

Incremental profile update after a session ends. Appends to the rolling session log and updates domain profile via EMA.

**Input Schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | **Yes** | Unique session identifier |
| `domain` | string | No | Domain override |
| `tools_used` | array | No | List of tool names used |
| `duration` | number | No | Session duration in milliseconds |
| `turn_count` | number | No | Number of conversation turns |
| `keywords` | array | No | Session keywords for categorization |
| `cwd` | string | No | Working directory |
| `project` | string | No | Project ID |

**Target Latency:** <200ms

---

### `get_methodology_graph`

Returns graph data for 3D visualization of the methodology map.

**Input Schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `domain` | string | No | Focus on a specific domain |

**Target Latency:** <100ms

---

### `open_visualization`

Launches the 3D methodology map in the default browser.

**Input Schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `domain` | string | No | Focus domain for initial view |

---

### `explore_features`

Interpretability exploration across four modes.

**Input Schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `mode` | string | **Yes** | One of: `features`, `attribution`, `persona`, `crosscoder` |
| `domain` | string | No | Target domain |
| `compare_domain` | string | No | Comparison domain (for crosscoder mode) |

**Modes:**

- **`features`** — Sparse dictionary features and their activations
- **`attribution`** — Pipeline attribution graph via perturbation tracing
- **`persona`** — 12D persona vector with drift detection
- **`crosscoder`** — Cross-domain persistent behavioral features

**Target Latency:** <100ms

---

### `open_memory_dashboard`

Launches the real-time memory dashboard in the default browser. Shows heat map, entity graph, and activity feed.

**Input Schema:** *(no parameters)*

---

### `remember`

Store a memory through the predictive coding write gate.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `content` | string | **Yes** | — | Memory content to store |
| `tags` | array | No | `[]` | Tags for classification |
| `directory` | string | No | `""` | Project directory context |
| `domain` | string | No | `""` | Domain override |
| `source` | string | No | `"user"` | Source identifier |
| `force` | boolean | No | `false` | Bypass the write gate |

**Target Latency:** <100ms

---

### `recall`

Retrieve memories using 6-signal WRRF fusion (vector + FTS5 + heat + Hopfield + HDC + SR).

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | **Yes** | — | Search query |
| `domain` | string | No | — | Filter by domain |
| `directory` | string | No | — | Filter by directory |
| `max_results` | integer | No | `10` | Maximum results to return |
| `min_heat` | float | No | `0.05` | Minimum heat threshold |

**Target Latency:** <200ms

---

### `consolidate`

Run memory maintenance: heat decay, compression, CLS consolidation, and optionally sleep compute.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `decay` | boolean | No | `true` | Run heat decay cycle |
| `compress` | boolean | No | `true` | Run compression pipeline |
| `cls` | boolean | No | `true` | Run CLS episodic→semantic consolidation |
| `memify` | boolean | No | `true` | Run memification cycle |
| `deep` | boolean | No | `false` | Enable sleep compute (dream replay, cluster summarization, re-embedding) |

**Target Latency:** <5s

---

### `checkpoint`

Save or restore working state for hippocampal replay.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `action` | string | **Yes** | — | `"save"` or `"restore"` |
| `directory` | string | No | `""` | Project directory |
| `current_task` | string | No | `""` | Current task description |
| `files_being_edited` | array | No | `[]` | Files currently being edited |
| `key_decisions` | array | No | `[]` | Key decisions made |
| `open_questions` | array | No | `[]` | Unresolved questions |
| `next_steps` | array | No | `[]` | Planned next steps |
| `active_errors` | array | No | `[]` | Active errors/blockers |
| `custom_context` | string | No | `""` | Additional context |
| `session_id` | string | No | `"default"` | Session identifier |

**Target Latency:** <100ms

---

### `narrative`

Generate project narrative from stored memories.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | string | No | — | Project directory |
| `domain` | string | No | — | Domain filter |
| `brief` | boolean | No | `false` | Generate brief summary only |

**Target Latency:** <500ms

---

### `memory_stats`

Memory system diagnostics.

**Input Schema:** *(no parameters)*

**Target Latency:** <50ms

---

### `import_sessions`

Import conversation history into the memory store.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `project` | string | No | `""` | Filter by project |
| `domain` | string | No | `""` | Domain override |
| `min_importance` | float | No | `0.4` | Minimum importance threshold |
| `max_sessions` | integer | No | `0` | Max sessions to import (0=unlimited) |
| `dry_run` | boolean | No | `false` | Preview without importing |
| `full_read` | boolean | No | `false` | Read full JSONL files (not head/tail) |

---

### `forget`

Delete or soft-delete a memory by ID. Respects `is_protected` guard — anchored memories require `force=True`.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `memory_id` | integer | **Yes** | — | Memory ID to delete |
| `soft` | boolean | No | `false` | Soft-delete (set heat to 0) instead of hard delete |
| `force` | boolean | No | `false` | Override is_protected guard |

**Target Latency:** <50ms

---

### `validate_memory`

Validate memories against current filesystem state. Detects stale file references.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `memory_id` | integer | No | — | Validate a specific memory |
| `domain` | string | No | — | Validate all memories in domain |
| `directory` | string | No | — | Validate by directory |
| `base_dir` | string | No | `""` | Base directory for relative path resolution |
| `staleness_threshold` | float | No | `0.5` | Staleness score threshold for flagging |
| `dry_run` | boolean | No | `false` | Preview without modifying |

**Target Latency:** <500ms

---

### `rate_memory`

Rate a memory as useful or not to update metamemory confidence.

**Input Schema:**

| Field | Type | Required | Description |
|---|---|---|---|
| `memory_id` | integer | **Yes** | Memory ID to rate |
| `useful` | boolean | **Yes** | Whether the memory was useful |

**Target Latency:** <50ms

---

### `seed_project`

Bootstrap memory from an existing codebase. Runs 5 stages: structure scan, entry point detection, config extraction, documentation parsing, and CI/CD detection.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | string | No | `""` | Codebase directory to seed from |
| `domain` | string | No | `""` | Domain override |
| `max_file_size_kb` | integer | No | `64` | Maximum file size to process |
| `dry_run` | boolean | No | `false` | Preview without creating memories |

---

### `anchor`

Mark a memory as compaction-resistant (heat=1.0, is_protected=True). Anchored memories are always surfaced at session start.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `memory_id` | integer | **Yes** | — | Memory ID to anchor |
| `reason` | string | No | `""` | Reason for anchoring |

**Target Latency:** <50ms

---

### `backfill_memories`

Auto-import prior Claude Code conversations into the memory store. Idempotent — skips already-processed files.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `project` | string | No | `""` | Filter by project |
| `max_files` | integer | No | `20` | Maximum conversation files to process |
| `min_importance` | float | No | `0.35` | Minimum importance threshold |
| `dry_run` | boolean | No | `false` | Preview without importing |
| `force_reprocess` | boolean | No | `false` | Re-process already-imported files |

---

## Tier 2 — Navigation & Exploration

### `recall_hierarchical`

Retrieve memories using fractal hierarchy with adaptive level weighting.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | **Yes** | — | Search query |
| `domain` | string | No | — | Filter by domain |
| `max_results` | integer | No | `10` | Maximum results |
| `min_heat` | float | No | `0.05` | Minimum heat threshold |
| `cluster_threshold` | float | No | `0.6` | Clustering distance threshold |

**Target Latency:** <200ms

---

### `drill_down`

Navigate into a fractal memory cluster (L2 → L1 → memories).

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `cluster_id` | string | **Yes** | — | Cluster ID to drill into |
| `domain` | string | No | — | Domain filter |
| `min_heat` | float | No | `0.05` | Minimum heat threshold |

**Target Latency:** <100ms

---

### `navigate_memory`

Navigate memory space using Successor Representation co-access patterns.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `memory_id` | integer | **Yes** | — | Starting memory ID |
| `max_depth` | integer | No | `2` | BFS traversal depth |
| `include_2d_map` | boolean | No | `false` | Include 2D eigendecomposition projection |
| `window_hours` | float | No | `2.0` | Co-access window in hours |

**Target Latency:** <200ms

---

### `get_causal_chain`

Trace entity relationships through the knowledge graph.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `entity_name` | string | No | — | Start from an entity name |
| `memory_id` | integer | No | — | Start from a memory's entities |
| `relationship_types` | array | No | — | Filter by relationship type |
| `max_depth` | integer | No | `3` | Maximum traversal depth |
| `direction` | string | No | `"both"` | `"outgoing"`, `"incoming"`, or `"both"` |

**Target Latency:** <200ms

---

### `detect_gaps`

Identify knowledge gaps: isolated entities, sparse domains, temporal drift.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `domain` | string | No | — | Focus on a specific domain |
| `include_entity_gaps` | boolean | No | `true` | Check for isolated entities |
| `include_domain_gaps` | boolean | No | `true` | Check for sparse domains |
| `include_temporal_gaps` | boolean | No | `true` | Check for temporal drift |
| `stale_threshold_days` | integer | No | `30` | Days before a domain is considered stale |

**Target Latency:** <500ms

---

## Tier 3 — Automation & Intelligence

### `sync_instructions`

Push top memory insights into CLAUDE.md for the project.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | string | No | `""` | Project directory |
| `max_insights` | integer | No | `10` | Maximum insights to include |
| `min_heat` | float | No | `0.3` | Minimum heat for inclusion |
| `dry_run` | boolean | No | `false` | Preview without writing |

**Target Latency:** <500ms

---

### `create_trigger`

Create a prospective memory trigger. Triggers fire automatically when conditions are met.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `content` | string | **Yes** | — | Memory content to surface when triggered |
| `trigger_condition` | string | **Yes** | — | Condition expression |
| `trigger_type` | string | No | `"keyword"` | `"keyword"`, `"time"`, `"file"`, or `"domain"` |
| `target_directory` | string | No | — | Limit trigger to a specific directory |

**Target Latency:** <100ms

---

### `add_rule`

Add a neuro-symbolic rule to the memory store.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `condition` | string | **Yes** | — | Rule condition expression |
| `action` | string | **Yes** | — | Action to take (boost/suppress/tag) |
| `rule_type` | string | No | `"soft"` | `"soft"` (weight adjustment) or `"hard"` (filter) |
| `scope` | string | No | `"global"` | `"global"`, `"domain"`, or `"directory"` |
| `scope_value` | string | No | — | Scope qualifier (domain name or directory path) |
| `priority` | integer | No | `0` | Higher priority rules are evaluated first |

**Target Latency:** <100ms

---

### `get_rules`

List active neuro-symbolic rules.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `scope` | string | No | — | Filter by scope |
| `rule_type` | string | No | — | Filter by type |
| `include_inactive` | boolean | No | `false` | Include disabled rules |

**Target Latency:** <50ms

---

### `get_project_story`

Generate a period-based autobiographical narrative of project activity.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | string | No | — | Project directory |
| `domain` | string | No | — | Domain filter |
| `period` | string | No | `"week"` | `"day"`, `"week"`, `"month"`, or `"all"` |
| `max_chapters` | integer | No | `5` | Maximum chapters to generate |

**Target Latency:** <500ms

---

### `assess_coverage`

Evaluate knowledge coverage completeness for a project.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | string | No | `""` | Project directory |
| `domain` | string | No | `""` | Domain filter |
| `stale_days` | integer | No | `14` | Days before knowledge is considered stale |

**Target Latency:** <500ms

---

### `run_pipeline`

Drives the ai-architect pipeline end-to-end through 11 stages.

**Input Schema:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `codebase_path` | string | **Yes** | — | Path to the codebase |
| `task_path` | string | **Yes** | — | Path to task specification |
| `context_path` | string | No | — | Additional context file |
| `github_repo` | string | No | — | GitHub repo for PR creation |
| `server` | string | No | `"ai-architect"` | MCP server name |
| `max_findings` | number | No | `5` | Maximum findings to include |

**Pipeline Stages:**

1. `init` — Initialize ai-architect session
2. `discovery` — Codebase analysis and discovery
3. `impact` — Impact assessment
4. `strategy` — Strategy formulation
5. `prd` — PRD generation
6. `interview` — Stakeholder interview simulation
7. `verification` — Plan verification
8. `implementation` — Implementation execution
9. `hor` — Hands-on review (non-fatal)
10. `audit` — Quality audit (non-fatal)
11. `push` — Push to branch and create PR

---

## Error Codes

| Code | Meaning | When |
|---|---|---|
| `-32600` | Invalid request | Malformed JSON-RPC |
| `-32601` | Method not found | Unknown MCP method |
| `-32602` | Invalid params | Unknown tool name or missing required field |
| `-32603` | Internal error | Unhandled exception |

## Error Types

The server uses a typed error hierarchy:

| Error Class | Description |
|---|---|
| `MethodologyError` | Base error for all methodology operations |
| `ValidationError` | Invalid input arguments |
| `StorageError` | Filesystem/database persistence failures |
| `AnalysisError` | Core analysis failures |
| `McpConnectionError` | MCP client connection failures |
