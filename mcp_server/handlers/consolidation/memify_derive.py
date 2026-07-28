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

from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.core.curation import identify_derivable_facts
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)

# Candidacy threshold for "high-weight" relationships -- reuses
# `identify_derivable_facts`'s own tested default (core/curation.py), not a
# new invented constant.
_WEIGHT_THRESHOLD = 10.0

# Bounded scan of relationship candidates before dedup/derivation. Mirrors
# the bounded-I/O convention already applied to tag-scoped reads elsewhere
# in this codebase (pg_store_queries.get_memories_by_tag, audit 2026-06-09).
_CANDIDATE_SCAN_LIMIT = 500

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
_MAX_DERIVATIONS_PER_RUN = 20

# Cap on `derived-src:<memory_id>` provenance tags per derived fact, split
# evenly across the relationship's two endpoint entities (highest-heat
# memories first, per get_memories_for_entity's ORDER BY heat_base DESC).
# Source: measured live-proof 2026-07-10, same throwaway DB as above -- 3
# source memories seeded per entity, all 6 came through untruncated
# (2 entities x 3 = 6), so the cap was set to exactly the observed
# per-entity provenance depth rather than an arbitrary round number. See
# /memories/engineer/inc6.1b-memify-derivation.md for the raw row.
_PROVENANCE_SRC_CAP = 6

_EMPTY_DERIVATION_STATS: dict[str, Any] = {
    "candidates_scanned": 0,
    "already_derived": 0,
    "derived_created": 0,
    "derived_rejected": 0,
    "derived_error": 0,
}


async def run_memify_derivation_cycle(store: MemoryStore) -> dict[str, Any]:
    """Derive new facts from high-weight relationships, gated via `remember()`.

    Precondition: `store` exposes `acquire_batch`, `get_all_entities`,
    `get_memories_for_entity`; `get_memories_by_tag` is optional (its
    absence degrades idempotence-checking to "nothing known yet", never to
    an error).

    Postcondition: always returns the five counters in
    `_EMPTY_DERIVATION_STATS`. `derived_created` memories are new rows,
    each carrying a `derived-rel:...` marker unique across the store
    (idempotence). Never raises -- a failure at any stage degrades to the
    zero/partial stats dict plus a logged exception, consistent with the
    rest of the memify cycle's best-effort posture.
    """
    stats = dict(_EMPTY_DERIVATION_STATS)
    try:
        relationships = _fetch_candidate_relationships(
            store, _WEIGHT_THRESHOLD, _CANDIDATE_SCAN_LIMIT
        )
    except Exception:
        logger.exception("memify derivation: failed to fetch candidate relationships")
        return stats
    if not relationships:
        return stats
    stats["candidates_scanned"] = len(relationships)

    try:
        entity_names = {
            e["id"]: e.get("name", "?") for e in store.get_all_entities(min_heat=0.0)
        }
    except Exception:
        logger.exception("memify derivation: failed to load entity names")
        return stats

    derived_markers = _existing_derived_markers(store)

    attempts = 0
    for rel in relationships:
        if attempts >= _MAX_DERIVATIONS_PER_RUN:
            break
        marker = _relationship_marker(rel)
        if marker in derived_markers:
            stats["already_derived"] += 1
            continue
        facts = identify_derivable_facts([rel], entity_names, _WEIGHT_THRESHOLD)
        if not facts:
            continue
        attempts += 1
        outcome = await _derive_one(store, rel, facts[0], marker)
        stats[outcome] += 1
    return stats


def _relationship_marker(rel: dict[str, Any]) -> str:
    """Deterministic provenance/idempotence key for one relationship."""
    return (
        f"derived-rel:{rel['source_entity_id']}-{rel['target_entity_id']}"
        f"-{rel['relationship_type']}"
    )


def _tags_of(mem: dict[str, Any]) -> list[str]:
    """Decode a memory's tags whether stored as list or JSON string."""
    tags = mem.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    return [str(t) for t in tags]


def _existing_derived_markers(store: MemoryStore) -> set[str]:
    """Return every `derived-rel:...` marker already present in the store.

    Degrades to the empty set (never an error) when the backend has no
    `get_memories_by_tag` (SQLite fallback) or the query itself fails --
    matching the existing `hasattr` guard convention
    (handlers/ingest_helpers.py::find_cached_graph).
    """
    try:
        if not hasattr(store, "get_memories_by_tag"):
            return set()
        mems = store.get_memories_by_tag("derived", limit=_CANDIDATE_SCAN_LIMIT)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("memify_derive.derived_markers", exc)
        return set()
    markers: set[str] = set()
    for mem in mems:
        for tag in _tags_of(mem):
            if tag.startswith("derived-rel:"):
                markers.add(tag)
    return markers


def _fetch_candidate_relationships(
    store: MemoryStore, threshold: float, limit: int
) -> list[dict[str, Any]]:
    """High-weight relationships, highest weight first. Same acquire_batch +
    raw-SQL pattern as memify.py's `_reweight_relationships`."""
    with store.acquire_batch() as conn:
        rows = conn.execute(
            "SELECT id, source_entity_id, target_entity_id, relationship_type, "
            "weight FROM relationships WHERE weight >= %s "
            "ORDER BY weight DESC LIMIT %s",
            (threshold, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def _provenance_memory_ids(store: MemoryStore, rel: dict[str, Any]) -> list[int]:
    """Up to `_PROVENANCE_SRC_CAP` memory ids that ground this relationship,
    split evenly across its two endpoint entities."""
    ids: list[int] = []
    per_entity_cap = max(1, _PROVENANCE_SRC_CAP // 2)
    for entity_id in (rel["source_entity_id"], rel["target_entity_id"]):
        try:
            mems = store.get_memories_for_entity(entity_id)
        except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
            silent_failure.note("memify_derive.provenance_memories", exc)
            mems = []
        for mem in mems[:per_entity_cap]:
            mid = mem.get("id")
            if mid is not None:
                ids.append(int(mid))
    return ids


async def _derive_one(
    store: MemoryStore, rel: dict[str, Any], fact_text: str, marker: str
) -> str:
    """Attempt to store one derived fact through the real write gate.

    Returns the stats key to increment: "derived_created" (stored, any
    action -- create/link/merge all count as the fact landing in the
    corpus) or "derived_rejected" (gate said no -- a valid outcome) or
    "derived_error" (the remember call itself raised).
    """
    from mcp_server.handlers.remember import handler as remember_handler

    src_ids = _provenance_memory_ids(store, rel)
    tags = ["derived", marker] + [f"derived-src:{mid}" for mid in src_ids]
    try:
        result = await remember_handler(
            {
                "content": fact_text,
                "tags": tags,
                "source": "consolidation",
                # M-D2 (7.4): this pathway IS the memify-derive machine
                # synthesis — explicit, no source-string re-derivation.
                "write_class": "derived",
                "force": False,
            }
        )
    except Exception:
        logger.exception("memify derivation: remember() raised for %s", marker)
        return "derived_error"
    return "derived_created" if result.get("stored") else "derived_rejected"
