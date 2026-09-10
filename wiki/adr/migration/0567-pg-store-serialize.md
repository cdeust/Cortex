---
kind: adr
number: 0567
title: Preserve pg_store_serialize design decisions
status: accepted
---

# ADR-0567: pg_store_serialize design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_serialize.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1 cap)
— these are the conversions every read/write path in the other pg_store_*
mixins ultimately funnels through, so they get their own cohesive module
rather than living inside any single caller.

````

### _isoformat_datetime_fields, original line 81

````text
        Precondition: none. Postcondition: for every ``f`` in ``fields``,
        ``d[f]`` is never a ``datetime.datetime`` instance -- either it was
        already something else (str, None, absent), or it is now its
        ``.isoformat()`` string. Every reader of a memory-row dict
        (WRRF candidates, direct get_memory() rows, SA-injected
        candidates) must go through this so a caller can compare/sort
        mixed-origin candidate lists without a type mismatch.
        
````

### comment, original line 44

````text
# pgvector>=0.5.0 psycopg loaders return Vector, not ndarray
            # source: pgvector-python CHANGELOG 0.5.0 (2026-07-06)
````

### comment, original line 55

````text
# source: incident 2026-07-11 (garde x3 bench, LongMemEval), RCA in
    # ADR-0054's addendum -- recall_memories() (the WRRF path) returned
    # raw `dict(r)` rows with created_at still a psycopg
    # `datetime.datetime` object, while every other memory-row reader in
    # this class went through _normalize_memory_row and got an ISO
    # string. Both are candidate dicts that can sit in the SAME list
    # (recall_pipeline.spreading_activation_expand appends store.get_memory()
    # rows onto recall_memories()'s output for RRF blending) and reach
    # pg_recall.py::_chronological_rerank's `sorted(..., key=lambda c:
    # c.get("created_at"))` together -- `str < datetime` raises
    # unconditionally. The response schema for `recall`
    # (handlers/recall.py, "created_at": {"type": "string", "format":
    # "date-time"}) has always mandated the string form; recall_memories()
    # was the one path never honoring it. Fixed at the source (both
    # readers now share one normalizer) rather than patched at the sort.
````

### comment, original line 107

````text
# A3: expose heat_base as heat for Python callers that expect
        # the pre-A3 dict key. recall_memories() already returns heat
        # (via effective_heat); this handles direct SELECT paths.
````

### comment, original line 115

````text
# Ensure tags is a list
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
