---
name: cortex-explore-memory
description: "Explore the memory system's state, find gaps in knowledge, assess coverage, and get diagnostic information. Use when the user asks 'what does my memory look like', 'show me memory stats', 'what am I missing', 'how good is my knowledge', 'memory health', 'show coverage', 'find gaps', 'what topics are weak', or when you need to understand the state of stored knowledge before a task."
---

# Explore Memory — Diagnostics, Gaps, and Coverage

## Keywords
memory stats, diagnostics, coverage, gaps, what am I missing, memory health, knowledge gaps, weak areas, isolated entities, sparse domains, how much do I know, memory overview, system status, knowledge assessment

## Overview

Understand the state of your memory system — what's stored, what's missing, what's decaying, and where knowledge is strong or weak. This skill combines multiple diagnostic tools to give you a complete picture.

**Use this skill when:** Starting a new project phase, after a long break, or when you want to understand what Cortex knows and doesn't know about a topic.

## Workflow

### Step 1: Quick Health Check

Get system-level diagnostics:

```
cortex:memory_stats({})
```

Returns: total memories, heat distribution, store type breakdown (episodic vs semantic), entity count, relationship count, average confidence, and decay statistics.

### Step 2: Assess Knowledge Coverage

Score how well a topic or project is covered:

```
cortex:assess_coverage({
  "domain": "<project or topic>",
  "query": "<specific area to assess>"
})
```

Returns a 0-100 coverage score with specific recommendations on what to document or remember next.

### Step 3: Detect Knowledge Gaps

Find isolated entities, sparse domains, and temporal drift:

```
cortex:detect_gaps({
  "domain": "<optional domain filter>"
})
```

Returns:
- **Isolated entities** — entities mentioned but not connected to memories
- **Sparse domains** — project areas with few memories
- **Temporal gaps** — periods with no memory activity (potential knowledge loss)
- **Orphan clusters** — groups of memories disconnected from the main knowledge graph

### Step 4: Validate Against Filesystem

Check if memories reference files/paths that still exist:

```
cortex:validate_memory({
  "directory": "<project root>"
})
```

Flags stale memories that reference deleted files, moved modules, or renamed functions — keeping the knowledge base accurate.

### Step 5: Review Memory Quality

Get a narrative summary of what's stored:

```
cortex:narrative({
  "domain": "<project>",
  "style": "diagnostic"
})
```

Or get a period-based project story:

```
cortex:get_project_story({
  "domain": "<project>",
  "period": "last_30_days"
})
```

## Tips

- **Run after backfill**: After `cortex:backfill_memories`, run diagnostics to see what was captured and what's still missing
- **Coverage before deep work**: Before a major feature or refactor, assess coverage to know if you have enough context stored
- **Validate periodically**: Run `validate_memory` after major refactors to catch stale references
