# ADR-0365: mcp_server/handlers/consolidation/memify_derive.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/consolidation/memify_derive.py`; original SHA-256 `2e412a055bc08d00c754f27d595e84dc98ceba73bd057b42263bf5d237ec6eef`.

## Original docstring, lines 1–45

````text
"""Memify fact derivation: synthesize new memories from high-weight entity
relationships, routed through the production write gate.

Wires `identify_derivable_facts` (mcp_server/core/curation.py) into the
memify cycle so consolidate's schema description -- "extract reusable
lessons and rules from recent successes/failures" -- is actually true.
`identify_derivable_facts` was defined and unit-tested from its
introduction but never called outside tests until this module (gate
decision INC6.1b, 2026-07-10: wire it, don't delete it).

Contract:
  * Append-only. Every derived fact is a NEW memory row created via the
    real `remember` handler. The source relationship and its member
    entities/memories are never mutated.
  * Explicit provenance. Each derived memory carries two tag families:
    - ``derived-rel:<source_entity_id>-<target_entity_id>-<relationship_type>``
      (exactly one per relationship -- doubles as the idempotence key).
    - ``derived-src:<memory_id>`` for up to `_PROVENANCE_SRC_CAP` memories
      that mention either endpoint entity (highest-heat first). This is a
      tag, not a `relationships` row: the `relationships` table's FK is
      `REFERENCES entities(id)`, so it cannot address a memory id (this was
      the pre-existing, silently-failing bug in
      `handlers/consolidation/cls.py::_link_source_memories` and
      `handlers/remember_helpers.py::_link_if_needed` -- both passed memory
      ids into `insert_relationship` and swallowed the resulting FK
      violation in a bare `except Exception: pass`, so no such link was ever
      persisted; both were fixed to reuse this module's `derived-src:`
      convention instead, see fix/memory-link-fk-violation).
      `supersedes_id` is also wrong here: nothing is being replaced. Tags
      are the only mechanism in this schema that can carry a memory-id-
      shaped, SQL-queryable pointer without a FK.
  * Idempotent on STORED derivations. A relationship whose marker tag
    already exists on some memory is skipped before any gate call --
    verified by SQL, not by re-deriving and letting the gate dedupe.
  * Gate-honest. A relationship whose candidate fact was previously
    REJECTED by the write gate carries no marker (nothing was stored), so
    it is legitimately re-offered on a later run. This is bounded
    re-evaluation, not duplication: a marker tag is written if and only if
    a memory row exists for it.
  * Bounded. At most `_MAX_DERIVATIONS_PER_RUN` write-gate attempts (the
    expensive path: embedding + entity extraction + similarity search) per
    call, so one memify cycle cannot flood the gate.
  * Never overrides the gate. `force` is always False -- a rejection is a
    valid, counted outcome, not a bug to route around.
"""
````

## Original comment, lines 65–67

````text
# Bounded scan of relationship candidates before dedup/derivation. Mirrors
# the bounded-I/O convention already applied to tag-scoped reads elsewhere
# in this codebase (pg_store_queries.get_memories_by_tag, audit 2026-06-09).
````

## Original comment, lines 70–79

````text
# Max write-gate attempts (full `remember()` calls -- embedding + entity
# extraction + similarity search, the expensive path) per memify run.
# Source: measured live-proof 2026-07-10 against a throwaway PostgreSQL
# database (`cortex_derive_livetest`, schema-only, dropped after the proof
# -- the shared dev/prod `cortex` DB was never touched). 20 real gate
# attempts (mixed accept/reject) completed in 6.85s wall-clock, including
# one first-call embedding-model load -- 0.34s/attempt worst case, ~0.19s/
# attempt steady-state. 20 attempts therefore costs at most ~7s, well
# inside the "~5-60s typical" budget documented on consolidate's schema.
# Raw run: /memories/engineer/inc6.1b-memify-derivation.md.
````

## Original comment, lines 82–89

````text
# Cap on `derived-src:<memory_id>` provenance tags per derived fact, split
# evenly across the relationship's two endpoint entities (highest-heat
# memories first, per get_memories_for_entity's ORDER BY heat_base DESC).
# Source: measured live-proof 2026-07-10, same throwaway DB as above -- 3
# source memories seeded per entity, all 6 came through untruncated
# (2 entities x 3 = 6), so the cap was set to exactly the observed
# per-entity provenance depth rather than an arbitrary round number. See
# /memories/engineer/inc6.1b-memify-derivation.md for the raw row.
````

