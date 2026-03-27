---
name: cortex-consolidate
description: "Run memory maintenance — decay old memories, compress stale content, consolidate episodic memories into semantic knowledge, and run sleep-like replay. Use when the user says 'clean up memories', 'consolidate', 'run maintenance', 'compress old memories', 'memory cleanup', or periodically to keep the memory system healthy. Also use after importing many memories or at the end of a long session."
---

# Consolidate — Memory Maintenance and Evolution

## Keywords
consolidate, maintenance, cleanup, compress, decay, merge, evolve, sleep, replay, consolidation, memory health, prune, clean up, optimize memories, reduce noise

## Overview

Run the full memory maintenance pipeline — modeled after biological memory consolidation. This includes heat decay (cooling unused memories), compression (full text to gist to tags), CLS consolidation (episodic to semantic), causal graph discovery, and sleep-like replay that strengthens important memory clusters.

**Use this skill when:** After a long session, after bulk imports, periodically (weekly), or when memory_stats shows too many hot memories or high noise.

## Workflow

### Step 1: Run Full Consolidation

```
cortex:consolidate({})
```

This runs the complete pipeline:

1. **Decay cycle** — Cool memories by heat * decay_factor. Memories below cold threshold (0.05) become candidates for compression
2. **Compression** — Old memories compress through stages: full text (7+ days) to gist, gist (30+ days) to tags
3. **CLS consolidation** — Frequently-accessed episodic memories promote to semantic store (like hippocampal-to-cortical transfer)
4. **Causal discovery** — PC Algorithm runs on entity co-occurrences to discover causal relationships
5. **Sleep compute** — Dream-like replay strengthens clusters, summarizes related memories, and re-embeds compressed content

### Step 2: Review Results

The response includes:
- `memories_decayed` — how many cooled down
- `memories_compressed` — how many were compressed (and to what level)
- `memories_consolidated` — how many promoted from episodic to semantic
- `causal_edges_discovered` — new relationships found
- `replay_clusters` — memory clusters that were replayed and strengthened

### Step 3: Selective Operations

For targeted maintenance instead of the full pipeline:

**Forget specific memories:**
```
cortex:forget({
  "memory_id": <id>,
  "hard": false
})
```
Soft delete (sets heat to 0) by default. Use `"hard": true` for permanent deletion. Protected memories require explicit `"force": true`.

**Save checkpoint before risky operations:**
```
cortex:checkpoint({
  "action": "save",
  "label": "before-consolidation"
})
```

**Restore if something went wrong:**
```
cortex:checkpoint({
  "action": "restore",
  "label": "before-consolidation"
})
```

## Tips

- **Don't over-consolidate**: Running too frequently prevents memories from naturally developing heat signals. Weekly is usually sufficient.
- **Check stats first**: Run `cortex:memory_stats` before consolidating to understand what needs maintenance
- **Checkpoint before bulk operations**: Always save a checkpoint before consolidation if you have critical memories
- **After backfill**: Always consolidate after `cortex:backfill_memories` to process the imported memories through the full pipeline
