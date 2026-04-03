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

## Phase 2: Codebase Seeding

1. Call `cortex:seed_project({"directory": "<cwd>"})` where `<cwd>` is the current working directory.
2. Record the count of discoveries for the final summary.

## Phase 3: History Import

1. Call `cortex:backfill_memories({"dry_run": true, "max_files": 500})` to preview available session files.
2. If files are available, call `cortex:backfill_memories({"max_files": 500, "min_importance": 0.35})` to import.
3. Record the count of imported memories for the final summary.

## Phase 4: Consolidation and Verification

1. Call `cortex:consolidate({})` to run decay, compression, CLS, and causal discovery on all memories.
2. Call `cortex:memory_stats({})` to get the final system state.
3. Call `cortex:detect_gaps({})` to identify knowledge gaps.

## Final Summary

After all phases complete, print a single summary block:

```
Cortex Setup Complete
---------------------
Memories stored: <total from memory_stats>
Entities:        <count from memory_stats>
Relationships:   <count from memory_stats>
Gaps found:      <count and brief description from detect_gaps>
```

Do not print intermediate status updates between phases beyond what the tool calls themselves return. One summary at the end.
