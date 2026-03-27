---
name: cortex-remember
description: "Store important decisions, patterns, errors, lessons, and context into Cortex persistent memory. Use when the user says 'remember this', 'save this', 'store this for later', 'note this down', 'don't forget', 'this is important', 'bookmark this', or when a significant decision, bug fix, architecture choice, or lesson learned occurs during a session. Also use after resolving tricky bugs, making technology choices, or discovering important patterns."
---

# Remember — Store to Persistent Memory

## Keywords
remember, save, store, note, bookmark, don't forget, important, keep this, record, persist, write down, save for later, remember this decision, store this pattern, note this lesson, save this fix

## Overview

Store important information into Cortex's thermodynamic memory system. Memories pass through a predictive coding gate that automatically filters noise — only genuinely novel or important content gets stored. The system handles deduplication, entity extraction, and knowledge graph linking automatically.

**Use this skill when:** A significant event happens during a session — a decision is made, a bug is fixed, a pattern is discovered, or the user explicitly asks to remember something.

## Workflow

### Step 1: Identify What to Remember

Determine the content worth storing. Good candidates:
- **Decisions**: "We chose PostgreSQL over SQLite because..."
- **Bug fixes**: "The root cause was X, fixed by Y"
- **Patterns**: "This codebase uses factory injection for all handlers"
- **Lessons**: "Never use asyncio.get_event_loop() in Python 3.10+"
- **Context**: "The user prefers minimal PRs with focused changes"

### Step 2: Store the Memory

Call `cortex:remember` with structured content:

```
cortex:remember({
  "content": "<clear, self-contained description of what to remember>",
  "tags": ["<category>", "<project>", "<topic>"],
  "directory": "<current working directory>",
  "source": "<context: e.g. 'bug-fix', 'architecture-decision', 'user-preference'>"
})
```

**Content guidelines:**
- Write content that will make sense in 3 months without context
- Include the *why*, not just the *what*
- Keep it under 2000 characters
- Be specific: "PostgreSQL 15+ required for pgvector HNSW indexes" not "we use Postgres"

### Step 3: Verify Storage

The response includes:
- `stored: true/false` — whether the gate accepted it (false means too similar to existing memory)
- `memory_id` — the stored memory's ID
- `novelty_score` — how novel the content was vs existing memories
- `merged_with` — if it was merged into an existing memory instead of creating new

If `stored: false`, the content was likely redundant. This is normal — the gate is working.

### Step 4: Anchor Critical Memories (Optional)

For memories that must survive context compaction and never decay:

```
cortex:anchor({
  "memory_id": <id>,
  "reason": "Critical architecture decision — must persist"
})
```

Anchored memories maintain heat=1.0 permanently and are injected at every session start.

## Tips

- **Don't over-remember**: The predictive coding gate filters noise, but storing 50 trivial memories per session degrades retrieval quality
- **Tags matter**: Use consistent tags across sessions (e.g. `bug-fix`, `architecture`, `user-preference`, `lesson`) for better recall filtering
- **Force flag**: Pass `"force": true` to bypass the novelty gate when you know something is important despite seeming similar to existing memories
- **Rate memories later**: Use `cortex:rate_memory` with `useful: true/false` to train the system's metamemory confidence scoring
