---
kind: adr
number: 0579
title: Preserve pg_store_wiki_notes design decisions
status: accepted
---

# ADR-0579: pg_store_wiki_notes design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_wiki_notes.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of ``pg_store_wiki.py`` (originally 890 lines, over the
300-line file limit — CLAUDE.md "Code Quality Rules") purely for size
compliance; no logic changed.
````

### insert_citation, original line 32

````text
    Precondition: page_id references an existing wiki.pages row.
    Postcondition: two independent dedup keys apply, both enforced by
    partial unique indexes (pg_schema.py):
      - (page_id, session_id) where session_id <> '' — "this page was
        read in this session" (CITED_IN semantics, T2-H4/D7/Q2). The
        +0.05 heat bump on trg_wiki_citation_bump must not repeat per
        re-read within one session.
      - (page_id, memory_id) where memory_id IS NOT NULL — "this
        memory was reported as used to author/re-curate this page"
        (DOCUMENTS semantics, I6-D7/INC6.8). A re-curation reporting
        the same memory again for the same page must not grow the
        table.
    The INSERT omits an explicit conflict target (unqualified
    ``ON CONFLICT DO NOTHING``) so Postgres infers whichever partial
    index actually matches the row being inserted, without either
    write-path caller needing to know about the other's dedup key.
    Rows with session_id='' AND memory_id IS NULL carry no dedup
    semantics at all and always insert.
    Returns the new citation id, or None if either dedup key already
    had a matching row (duplicate, not an error).
    
````

### list_uncited_deliberate_memories, original line 106

````text
List active, deliberate, verifiably-important memories with zero
    wiki.citations rows — I6-D7's reverse loop ("orphelines délibérées").
````

### list_uncited_deliberate_memories, original line 106

````text
    Precondition: none (works on any wiki-schema-provisioned DB, even
    with zero citations rows).
    Postcondition: returns candidates for documentation, READ-ONLY —
    this function never writes a page or a citation; it is a report,
    not an action (D7 arbitrage: "pas d'écriture automatique de
    pages").
````

### list_uncited_deliberate_memories, original line 106

````text
    "Deliberate" mirrors ``core.write_post_store._AUTO_CAPTURE_SOURCES``
    (currently the sole canonical auto-capture source, 'post_tool_
    capture') rather than importing that private module-level constant
    across a core/infrastructure boundary for one string. "Important"
    is a disjunction over the signals available on the memories table
    TODAY: is_protected (anchor.py sets this), importance >= 0.8, or
    source_attribution = 'verified'. I6-D6 (validate_memory's
    provenance grader, a sibling increment) is expected to populate
    source_attribution with real 'verified'/'verifiable'/'unverifiable'
    values — this query already reads that column so it benefits
    automatically once D6 lands, without needing a schema change here.
    
````

### comment, original line 174

````text
# An aggregate SELECT always yields one row; None means the
            # backend broke its contract — surface it, never return a fake.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### list_uncited_deliberate_memories: final review

````text
Precondition: none (works on any wiki-schema-provisioned DB, even
    with zero citations rows). Postcondition: returns candidates for documentation,
    READ-ONLY —
    this function never writes a page or a citation; it is a report,
    not an action (D7 arbitrage: "pas d'écriture automatique de
    pages").

source: ADR-0579
````
