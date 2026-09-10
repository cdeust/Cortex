---
kind: adr
number: 0611
title: Preserve sqlite_store_mood design decisions
status: accepted
---

# ADR-0611: sqlite_store_mood design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/sqlite_store_mood.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
The supersession write path lives in SqliteMemoryStore.supersede_atomic (the
atomic insert+edge primitive), mirroring PgMemoryStore.
````

### module, original line 1

````text
All signatures mirror PgMemoryStore exactly (duck-type compatibility).

````

### SqliteMoodMixin, original line 25

````text
    Source references are on each method below.
    
````

### get_user_mood, original line 39

````text
        Mirrors PgMemoryStore.get_user_mood. None means the mood
        MOOD_CONGRUENT_RERANK stage should no-op (Bower 1981 requires a
        real mood; we never fabricate one).
        Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
        
````

### get_user_mood_state, original line 67

````text
        Mirrors PgMemoryStore.get_user_mood_state. Reserved for future
        stages that consume arousal (Russell 1980 circumplex). The
        MOOD_CONGRUENT_RERANK stage only uses valence via get_user_mood().
        Source: Russell, J.A. (1980). "A circumplex model of affect."
          J. Personality & Social Psychology 39(6), 1161-1178.
        
````

### set_user_mood, original line 100

````text
        Idempotent — repeated writes with the same value bump updated_at,
        which is the correct semantics for a "freshness of last observed
        mood" signal.
        Mirrors PgMemoryStore.set_user_mood.
        Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
        
````

### get_embeddings_for_memories, original line 133

````text
        Mirrors PgMemoryStore.get_embeddings_for_memories.
        Used by recall_pipeline.hopfield_complete to avoid per-ID round trips.
````

### get_embeddings_for_memories, original line 133

````text
        SQLite note: memories_vec is the sqlite-vec virtual table. When
        _has_vec is False the table does not exist and we return an empty
        dict (matching PG returning zero rows for embeddings that are NULL).
        We fetch one row at a time because sqlite-vec does not support WHERE
        rowid IN (...) batch queries in the versions available at fallback
        scale; the loop is bounded by len(memory_ids) which is capped by the
        recall pool size (typically <= 300).
        Engineering choice: individual rowid lookups are O(1) in sqlite-vec
        B-tree index — the loop is therefore O(N) with a small constant.
        
````

### comment, original line 33

````text
# ── User mood (Bower 1981 mood-congruent recall) ──────────────────
    # Mirrors PgMemoryStore: pg_recall._get_user_mood() duck-types against
    # get_user_mood() and consumes a scalar valence in [-1, +1].
    # Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
