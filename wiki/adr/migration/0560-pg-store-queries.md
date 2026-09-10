---
kind: adr
number: 0560
title: Preserve pg_store_queries design decisions
status: accepted
---

# ADR-0560: pg_store_queries design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_queries.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Streaming/chunked reads live in the sibling ``pg_store_query_stream``
module and entity co-access JOIN queries in ``pg_store_co_access``
(both split out by issue #407: this file was 401 lines over the
300-line §4.1 cap).

````

### get_all_memories_for_validation, original line 101

````text
        ``after_id`` is a cursor: pass the max ``id`` seen in the previous
        page to continue. Ordering is by ``id ASC`` (not ``last_accessed``)
        specifically so the cursor is stable across calls — last_accessed
        can change between pages if a validation pass itself touches rows.
        ``include_stale`` defaults False (unchanged behavior for existing
        callers — assess_coverage, change_impact); validate_memory passes
        True so a provenance re-check can rehabilitate (de-stale) a
        memory whose references all resolve again.
        
````

### _search_by_tag_vector_ranked, original line 163

````text
        current_memories: typed pool hits are inserted at rank 0 by the
        caller — a superseded instruction/preference served here would
        outrank its own correction, so exclusion at the source is the
        only safe placement.
        
````

### search_by_tag_vector, original line 203

````text
        ENGRAM (arxiv 2511.12960): per-type retrieval pools guarantee
        typed memories (preference, instruction) are not drowned out.
        Delegates to ``_search_by_tag_vector_ranked`` /
        ``_search_by_tag_vector_unranked`` depending on whether an
        embedding was supplied.
        
````

### delete_memories_by_tag, original line 221

````text
        precondition: tag is a non-empty string; domain is None or a non-empty string.
        postcondition: returns the number of rows removed; rows removed iff their
            tags JSONB contains [tag] AND (domain is None OR domain matches).
            domain=None preserves global-purge behavior for callers that
            actually want it (legacy contract). Caller is responsible for
            passing domain when scope matters (e.g. seed_project, which is
            per-repo by design — see issue #16).
        
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### delete_memories_by_tag: completeness audit

````text
Delete memories with the given tag, optionally scoped to a domain.

precondition: tag is a non-empty string; domain is None or a non-empty string.
        postcondition: returns the number of rows removed; rows removed iff
        their
            tags JSONB contains [tag] AND (domain is None OR domain matches).
            domain=None preserves global-purge behavior for callers that
            actually want it (legacy contract).

source: ADR-0560
````
