---
name: cortex-debug-memory
description: "Debug and fix memory system issues — validate memories, rate quality, manage protection, forget bad memories, and restore from checkpoints. Use when the user says 'fix memory', 'bad memory', 'wrong memory', 'delete this', 'protect this', 'this memory is wrong', 'memory quality', 'rate this memory', 'restore checkpoint', 'undo', or when memories are returning incorrect or stale results."
---

# Debug Memory — Fix, Rate, Protect, and Restore

## Keywords
debug, fix, bad memory, wrong, delete, forget, protect, rate, quality, restore, checkpoint, undo, stale, incorrect, mark useful, mark not useful, anchor, unprotect

## Overview

Tools for maintaining memory quality — rate memories as useful or not, protect critical ones from decay, forget incorrect ones, validate against the filesystem, and restore from checkpoints when things go wrong.

**Use this skill when:** Recall returns wrong results, memories are stale, you need to undo changes, or you want to improve retrieval quality through feedback.

## Workflow

### Fix Bad Memories

**Soft delete** (sets heat to 0, memory still exists but won't surface):
```
cortex:forget({
  "memory_id": <id>,
  "hard": false
})
```

**Hard delete** (permanent removal):
```
cortex:forget({
  "memory_id": <id>,
  "hard": true
})
```

Protected memories require `"force": true` to delete.

### Rate Memory Quality

Provide feedback to train the metamemory system:

```
cortex:rate_memory({
  "memory_id": <id>,
  "useful": true
})
```

Or mark as not useful:
```
cortex:rate_memory({
  "memory_id": <id>,
  "useful": false,
  "reason": "outdated — we no longer use this approach"
})
```

Ratings adjust the memory's confidence score, which affects future retrieval ranking. Over time, this trains the system to surface better results.

### Protect Critical Memories

**Anchor** a memory (heat=1.0 permanently, injected at session start):
```
cortex:anchor({
  "memory_id": <id>,
  "reason": "Core architecture decision — never decay"
})
```

### Validate Against Reality

Check if memories reference things that still exist:
```
cortex:validate_memory({
  "directory": "<project root>"
})
```

Returns a list of stale memories (referencing deleted files, moved modules, etc.) that should be forgotten or updated.

### Checkpoint and Restore

**Save a checkpoint** before risky operations:
```
cortex:checkpoint({
  "action": "save",
  "label": "before-cleanup"
})
```

**Restore** if something went wrong:
```
cortex:checkpoint({
  "action": "restore",
  "label": "before-cleanup"
})
```

**List available checkpoints:**
```
cortex:checkpoint({
  "action": "list"
})
```

Checkpoints are also created automatically before context compaction (via the compaction hook).

## Common Issues

**Recall returns irrelevant results:**
1. Rate the bad results as `useful: false`
2. Rate the good results as `useful: true`
3. Check if there are duplicate/conflicting memories on the same topic
4. Run `validate_memory` to find stale content

**Too many memories on the same topic:**
1. Run `cortex:consolidate` — CLS will merge similar episodic memories into semantic ones
2. Manually `forget` duplicates

**Memory seems wrong/outdated:**
1. Forget the old memory
2. Remember the corrected version
3. The knowledge graph will update automatically

**Lost important context after compaction:**
1. Check `cortex:checkpoint({ "action": "list" })` for auto-checkpoints
2. Restore the most recent pre-compaction checkpoint
3. Anchored memories survive compaction automatically
