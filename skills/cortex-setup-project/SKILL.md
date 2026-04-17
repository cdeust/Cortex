---
name: cortex-setup-project
description: "Bootstrap Cortex for a new project or import existing session history. Use when the user says 'set up Cortex', 'seed this project', 'import my history', 'backfill memories', 'bootstrap memory', 'initialize Cortex for this project', or when starting to use Cortex on an existing codebase that already has Claude Code conversation history."
---

# Setup Project — Fully Autonomous Bootstrap

Execute all four phases sequentially without asking the user any questions. If a phase fails, attempt automatic recovery before reporting the error. Never ask the user to run commands manually or choose between options.

## Phase 1: Infrastructure Verification

1. Run `pg_isready` via bash to check if PostgreSQL is running.
2. Call `cortex:memory_stats({})` to verify database connectivity.
3. If **either** check fails:
   - Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh"` automatically. Do not ask for permission.
   - After setup.sh completes, call `cortex:memory_stats({})` again to verify.
   - If it still fails, report the error output and **stop**. Do not continue to later phases.
4. If both checks pass, proceed to Phase 2.

## Phase 2: Build Methodology Profiles

1. Call `cortex:rebuild_profiles({"force": true})` to scan all session history and build cognitive profiles per domain.
2. This creates the domain hubs that memories, entities, and discussions link to. It must run before seeding.
3. Record the domain count for the final summary.

## Phase 3: Codebase Seeding

1. Call `cortex:seed_project({"directory": "<cwd>"})` where `<cwd>` is the current working directory.
2. Record the count of discoveries for the final summary.

### Phase 3b: Pipeline Codebase Analysis (Optional)

The ai-automatised-pipeline MCP server provides structured codebase analysis (symbol graph, processes, communities, cross-file impact). It is optional — Cortex core memory/recall works without it. Enable only if the user asks for "deeper code understanding", "symbol-level memory", or the codebase is large (>5k files) where substring-based hooks underperform.

1. Detection: attempt `cortex:ingest_codebase({"project_path": "<cwd>"})`. If it succeeds, record the counts (wiki pages, memory entities, KG edges) for the summary and skip to Phase 4.
2. If `ingest_codebase` fails with `McpConnectionError` (pipeline not installed/configured):
   - Check if the sibling checkout exists at `../anthropic/ai-automatised-pipeline/Cargo.toml` (or equivalent). If so, run `bash -c 'cd ../anthropic/ai-automatised-pipeline && cargo install --path . 2>&1 | tail -20'` (accepts ~1-2 min compile) and re-run the ingest.
   - If the source checkout is missing or cargo is unavailable, **skip Phase 3b silently** and proceed to Phase 4. Do NOT block setup on this.
3. The pipeline's auto-wire happens on every SessionStart via `pipeline_discovery`, so once the binary exists on PATH (or sibling source is built), future sessions pick it up automatically. No manual mcp-connections.json editing needed.

## Phase 4: History Import

1. Call `cortex:backfill_memories({"dry_run": true, "max_files": 500})` to preview available session files.
2. If files are available, call `cortex:backfill_memories({"max_files": 500, "min_importance": 0.35})` to import.
3. Record the count of imported memories for the final summary.

## Phase 5: Consolidation and Verification

1. Call `cortex:consolidate({})` to run decay, compression, CLS, and causal discovery on all memories.
2. Call `cortex:memory_stats({})` to get the final system state.
3. Call `cortex:detect_gaps({})` to identify knowledge gaps.

## Final Summary

After all phases complete, print a single summary block:

```
Cortex Setup Complete
---------------------
Domains:         <count from rebuild_profiles>
Memories stored: <total from memory_stats>
Entities:        <count from memory_stats>
Relationships:   <count from memory_stats>
Pipeline:        <"active — N wiki pages, M memories" | "skipped (not installed)">
Gaps found:      <count and brief description from detect_gaps>
```

Do not print intermediate status updates between phases beyond what the tool calls themselves return. One summary at the end.
