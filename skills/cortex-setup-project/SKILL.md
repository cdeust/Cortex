---
name: cortex-setup-project
description: "Bootstrap Cortex for a new project or import existing session history. Use when the user says 'set up Cortex', 'seed this project', 'import my history', 'backfill memories', 'bootstrap memory', 'initialize Cortex for this project', or when starting to use Cortex on an existing codebase that already has Claude Code conversation history."
---

# Setup Project — Bootstrap and Import

## Keywords
setup, seed, bootstrap, import, backfill, initialize, new project, import history, import sessions, first time, getting started, onboard, configure

## Overview

Get Cortex up and running for a project — either by seeding from the codebase structure or by importing existing Claude Code conversation history into persistent memory. This is typically done once per project.

**Use this skill when:** First time using Cortex on a project, or when you want to import historical conversations that happened before Cortex was installed.

## Workflow

### Option A: Seed from Codebase (New Project)

For projects with no prior Claude Code history, bootstrap from the code itself:

```
cortex:seed_project({
  "directory": "<project root>",
  "depth": "full"
})
```

This 5-stage pipeline:
1. **Scan** — Discover project structure, key files, dependencies
2. **Extract** — Pull architecture patterns, naming conventions, module boundaries
3. **Classify** — Detect domain, language, framework, paradigm
4. **Store** — Create foundational memories about the project's structure
5. **Link** — Build initial knowledge graph from extracted entities

### Option B: Backfill from History (Existing Project)

For projects with existing Claude Code conversations in `~/.claude/projects/`:

**Step 1: Preview what's available**
```
cortex:backfill_memories({
  "dry_run": true,
  "max_files": 500
})
```

Shows how many session files exist and how many memories would be extracted.

**Step 2: Run the import**
```
cortex:backfill_memories({
  "max_files": 500,
  "min_importance": 0.35
})
```

Extracts decisions, bug fixes, architecture discussions, and lessons from past conversations. Idempotent — already-processed files are skipped.

**Step 3: Filter to specific project (optional)**
```
cortex:backfill_memories({
  "project": "-Users-you-myproject",
  "max_files": 200
})
```

### Option C: Import Session Transcripts

For importing specific conversation data:

```
cortex:import_sessions({
  "directory": "<path to session data>"
})
```

### Step 3: Post-Import Consolidation

After any import, run consolidation to process the new memories:

```
cortex:consolidate({})
```

This decays irrelevant memories, compresses old content, discovers causal relationships, and promotes frequently-referenced memories.

### Step 4: Verify Import Quality

```
cortex:memory_stats({})
```

Check total memories, domain distribution, and entity count. Then:

```
cortex:detect_gaps({})
```

Find what's still missing and decide if you need to manually `cortex:remember` key context.

## Tips

- **Backfill is idempotent**: Run it multiple times safely — already-processed files are tracked by hash
- **Lower min_importance for more coverage**: Default 0.35 captures decisions and fixes. Set to 0.2 for broader coverage including context and discussions
- **Seed + Backfill complement each other**: Seed captures project structure, backfill captures session history
- **Always consolidate after import**: Raw imported memories need processing through the full biological pipeline
