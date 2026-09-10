---
kind: adr
number: 0557
title: Preserve pg_store_near_dup design decisions
status: accepted
---

# ADR-0557: pg_store_near_dup design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_near_dup.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Near-duplicate candidate pair scan — DB operations (I6-D2, INC6.4).
````

### module, original line 1

````text
Measures cosine similarity between active memories' embeddings and
returns candidate pairs above a floor similarity. Split into its own
module for the same reason as ``pg_store_memory_dedup.py`` (I6-D1
precedent): keep each infrastructure file focused and under the size
cap.
````

### module, original line 1

````text
Method (documented per coding-standards.md §8 — "no source, no
implementation" applies to methodology too, not just constants): an
exhaustive O(n^2) pairwise cosine scan over ~10k active memories is
~50M comparisons — computationally unreasonable for a one-shot campaign
query. Instead, for every active memory this module asks the existing
HNSW index (``idx_memories_embedding``, ``pg_schema.py:707-708``,
``vector_cosine_ops``) for its own top-K approximate nearest neighbors
via a LATERAL join — the same ORDER BY <=> LIMIT K pattern the
production WRRF recall query already uses for a single query embedding
(``pg_schema.py``'s ``recall_memories()``), just run once per row
instead of once per user query. This is an approximation: a pair whose
true cosine similarity is above the floor but where neither side ranks
in the other's top-K is missed. K=30 was chosen because a manual check
(2026-07-10, ad hoc `EXPLAIN ANALYZE` against this DB) showed the
0.75-similarity candidate set per row saturates well under 30 members
for every sampled anchor; this is a bound, not a proof of completeness,
and is documented as such in the campaign artifact (I6-D2 step 2:
"documente la methode").

````

### list_candidate_pairs, original line 61

````text
    Pre-condition:  ``top_k`` >= 1; ``min_similarity`` in [0, 1].
    Post-condition: returns one ``CandidatePair`` per undirected pair
                    found by EITHER side's top-K scan (a pair is kept if
                    it surfaces from A's neighbor scan OR B's — the
                    LATERAL join is directional per anchor row, so the
                    UNION via ``id_a < id_b`` + `DISTINCT` recovers the
                    undirected pair even when only one direction's top-K
                    happens to include it). Scoped to
                    ``current_memories WHERE NOT is_stale AND embedding
                    IS NOT NULL`` on both sides. No self-pairs. Ordered
                    by ``(id_a, id_b)`` for deterministic downstream
                    stratified sampling.
    
````

### fetch_contents, original line 120

````text
    Post-condition: returns ``{id: content}`` for every id in ``ids``
                    that still exists in ``current_memories``; ids that
                    no longer exist (superseded between scan and fetch)
                    are simply absent from the returned dict — the
                    caller must handle a missing key, not assume
                    completeness.
    
````

### fetch_member_stats, original line 140

````text
    Reuses the exact same CTE-hop pattern as
    ``pg_store_memory_dedup.list_exact_duplicate_groups`` (re-project
    ``current_memories`` through an anonymous-RECORD CTE before calling
    ``effective_heat()``, required because the view's composite type does
    not implicitly cast to the ``memories`` table type — see that
    module's docstring for the full explanation).
````

### fetch_member_stats, original line 140

````text
    Post-condition: returns ``{id: {"effective_heat": float,
                    "created_at": datetime}}`` for every id in ``ids``
                    still present in ``current_memories``; missing ids
                    (superseded concurrently) are simply absent.
    
````

### comment, original line 43

````text
# Per-anchor approximate-neighbor fan-out. See module docstring for the
# empirical justification (2026-07-10 EXPLAIN ANALYZE check on this DB).
````

### comment, original line 47

````text
# Bounds the number of anchor rows scanned in one pass (not the number of
# pairs produced) — mirrors DEFAULT_DEDUP_SCAN_LIMIT's rationale
# (pg_store_memory_dedup.py). 10024 active memories with embeddings
# measured 2026-07-10; comfortably under this cap.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### SQL literal, source line 98

````sql
-- M-D3 (7.1): homeostatic_state's PK is now (domain, write_class) —
-- without this filter the join fans out to one row per class and
-- COALESCE/effective_heat would see an arbitrary row, not the one
-- factor this table's readers were written for (auto is the only
-- class the fold/scalar mechanism regulates; see homeostatic.py).
````
