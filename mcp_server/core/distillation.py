"""Distillation dossier assembly — server-side candidate gathering for the
``curate_distill`` job; lesson AUTHORING stays with the in-session LLM
(M-D8).

Design doc: ``scratchpad/memoire-qui-comprend-design.md`` §M-D8. Mirrors the
role-split already proven by ``core/auto_curator.py`` (server clusters, the
in-session LLM authors, ``wiki_write``/``remember`` persists) — the only
distillation mechanism in this system that has ever produced anything: 0
rows from ``memify_derive``'s server-only templated synthesis (measured
2026-07-10, ``SELECT count(*) FROM memories WHERE tags @> '"derived"'``)
versus N wiki pages authored through ``curate_wiki``. ``curate_distill``
(handler) assembles three kinds of candidate "dossier" — pre-existing
evidence that a lesson-shaped synthesis is possible — and returns them as
jobs; the session LLM writes the WHY as a normal ``remember`` call
(``write_class='deliberate'``, tags ``lesson`` + ``derived-src:<id>``,
per M-D8 point 2 — NOT ``write_class='derived'``, which stays reserved for
``memify_derive``'s own machine-synthesized inventory facts, M-D8 point 3).

Pure business logic — no I/O. Every ``build_*_dossiers`` function receives
pre-fetched memory dicts / co-access pairs and returns ``DistillDossier``
objects; the handler (composition root) is the only layer that touches the
store.

Contract shared by every builder in this module:
  Precondition: inputs are pre-fetched (heads_only, not stale) by the
    caller; this module never queries a store.
  Postcondition: dossiers are capped (bounded-I/O convention, audit
    2026-06-09, mirrored from ``memify_derive.py``); a dossier's
    ``memory_ids`` are deduplicated and sorted ascending on construction
    (``DistillDossier.__post_init__``) because ``marker`` — the
    idempotence key — is a hash of that canonical order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from mcp_server.shared.hash import simple_hash
from mcp_server.core.auto_curator import extract_entities_from_content

if TYPE_CHECKING:
    from mcp_server.core.auto_curator import CurationCluster

# ── Bounds (source: bounded-I/O convention, audit 2026-06-09; mirrored
# from memify_derive.py's _CANDIDATE_SCAN_LIMIT / _MAX_DERIVATIONS_PER_RUN
# and auto_curator.py's MAX_MEMORIES_PER_PROMPT) ───────────────────────────
_MAX_DOSSIERS_PER_KIND = 10
_MAX_MEMORY_IDS_PER_DOSSIER = 12

# Error->success pairing: memories must share at least this many lexical
# entities (extract_entities_from_content) to count as "about the same
# thing". 1 is the minimum that means "related at all".
_MIN_SHARED_ENTITIES = 1

# Error->success search window. Source: reuses the existing system-wide
# maximum co-access window already established in
# handlers/navigate_memory.py's schema (`"maximum": 168.0` hours = 7
# days) as the search cap, rather than inventing a new constant. The
# curate_distill handler's dry-run measures the ACTUAL error->success gap
# distribution on the real corpus and reports it (see M-D9 gate: "VERDICT
# MESURABLE") instead of asserting a tuned default.
_DEFAULT_ERROR_SUCCESS_WINDOW_HOURS = 168.0

# "Recurring" co-access threshold. Source: reuses
# core/curation.py::identify_strengtheneable's existing `min_access: int =
# 5` default — the system's established threshold for "meaningfully
# revisited" — rather than inventing a second one for the same concept.
_MIN_RECURRING_ACCESS = 5
_MIN_CO_ACCESS_CLUSTER_SIZE = 3


def _parse_iso(ts: str | None) -> float:
    """ISO 8601 string -> Unix seconds; 0.0 on any parse failure.

    Precondition: none (accepts None/garbage).
    Postcondition: never raises. Mirrors
    ``core/cognitive_map.py::_parse_iso_timestamp`` (kept local rather
    than imported — a single stdlib-wrapping helper is not worth a
    core-to-core import; cognitive_map.py makes the same local-duplication
    choice for its own single call site).
    """
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def dossier_marker_tag(memory_ids: list[int]) -> str:
    """Deterministic idempotence marker for a dossier's member set.

    Precondition: ``memory_ids`` non-empty.
    Postcondition: the same set of ids (any input order, any duplicates)
    always maps to the same tag string. Extends
    ``memify_derive.py``'s ``derived-rel:<a>-<b>-<type>`` marker
    convention (INC6.1b, one marker per *pair*) to the N-member case,
    where a literal id-pair key is impossible — ``simple_hash``
    (``shared/hash.py``, DJB2, already used elsewhere for content
    fingerprinting) hashes the canonical (deduplicated, sorted) id list
    instead of a new hash primitive.
    """
    canonical = ",".join(str(i) for i in sorted(set(memory_ids)))
    return f"distill-of:{simple_hash(canonical)}"


@dataclass
class DistillDossier:
    """One candidate — evidence a lesson-shaped synthesis is possible.

    ``marker`` is this dossier's idempotence key (``dossier_marker_tag``
    of its canonical ``memory_ids``); the handler skips re-offering a
    dossier whose marker already exists as a tag on a stored memory (same
    skip-before-gate pattern as ``memify_derive._existing_derived_markers``).
    """

    kind: str  # "error_success" | "co_access_family" | "entity_family"
    topic: str
    domain: str
    memory_ids: list[int] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    avg_heat: float = 0.0
    marker: str = ""

    def __post_init__(self) -> None:
        self.memory_ids = sorted(set(int(i) for i in self.memory_ids))
        if not self.marker and self.memory_ids:
            self.marker = dossier_marker_tag(self.memory_ids)


def build_error_success_dossiers(
    error_memories: list[dict[str, Any]],
    success_memories: list[dict[str, Any]],
    window_hours: float = _DEFAULT_ERROR_SUCCESS_WINDOW_HOURS,
    max_dossiers: int = _MAX_DOSSIERS_PER_KIND,
) -> list[DistillDossier]:
    """Pair each error-tagged memory with the nearest LATER success-tagged
    memory sharing >= ``_MIN_SHARED_ENTITIES`` lexical entities within
    ``window_hours``.

    Precondition: both lists pre-fetched (any order — this function sorts
    internally); each memory dict carries ``id``, ``content``,
    ``created_at``, ``domain``.
    Postcondition: at most ``max_dossiers`` results, most-recent-error
    first; each dossier has exactly 2 ``memory_ids`` (error id, success
    id); a given success memory is consumed by at most one pairing
    (``used_success_ids``), so two errors never both claim the same fix.
    """

    def _entities(mem: dict[str, Any]) -> set[str]:
        return set(extract_entities_from_content(mem.get("content") or ""))

    errors = sorted(
        error_memories, key=lambda m: _parse_iso(m.get("created_at")), reverse=True
    )
    successes = sorted(success_memories, key=lambda m: _parse_iso(m.get("created_at")))
    success_entities = {
        s["id"]: _entities(s) for s in successes if s.get("id") is not None
    }
    window_secs = window_hours * 3600.0

    dossiers: list[DistillDossier] = []
    used_success_ids: set[int] = set()
    for err in errors:
        if len(dossiers) >= max_dossiers:
            break
        err_id = err.get("id")
        err_t = _parse_iso(err.get("created_at"))
        if err_id is None or err_t == 0.0:
            continue
        err_ents = _entities(err)
        if not err_ents:
            continue
        best: tuple[int, float, set[str]] | None = None  # (succ_id, delta, shared)
        for succ in successes:
            succ_id = succ.get("id")
            # succ_id == err_id: a memory tagged BOTH 'error' and
            # 'success' would otherwise "pair with itself" (delta=0,
            # trivially shares all its own entities) — found live on the
            # dev DB dry-run (INC7.8 verdict measurement), not a
            # hypothetical edge case.
            if succ_id is None or succ_id in used_success_ids or succ_id == err_id:
                continue
            delta = _parse_iso(succ.get("created_at")) - err_t
            if delta < 0 or delta > window_secs:
                continue
            shared = err_ents & success_entities.get(succ_id, set())
            if len(shared) < _MIN_SHARED_ENTITIES:
                continue
            if best is None or delta < best[1]:
                best = (succ_id, delta, shared)
        if best is None:
            continue
        succ_id, _delta, shared = best
        used_success_ids.add(succ_id)
        dossiers.append(
            DistillDossier(
                kind="error_success",
                topic=next(iter(sorted(shared)), "untitled"),
                domain=err.get("domain", ""),
                memory_ids=[int(err_id), int(succ_id)],
                entities=sorted(shared),
            )
        )
    return dossiers


class _UnionFind:
    """Minimal union-find for connected-components over co-access pairs.

    Precondition: none — ``find``/``union`` lazily create singleton
    components for unseen ids.
    Postcondition: path-compressed ``find`` keeps amortized near-O(1)
    lookups across the bounded (<= a few hundred edges) pair lists this
    module operates on.
    """

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def build_co_access_dossiers(
    pairs: list[tuple[int, int, float]],
    heat_by_id: dict[int, float] | None = None,
    min_cluster_size: int = _MIN_CO_ACCESS_CLUSTER_SIZE,
    max_dossiers: int = _MAX_DOSSIERS_PER_KIND,
) -> list[DistillDossier]:
    """Connected components over recurring co-access edges.

    Precondition: ``pairs`` is exactly
    ``store.get_temporal_co_access(min_access=_MIN_RECURRING_ACCESS,
    ...)``'s return shape (mem_a, mem_b, proximity) — the PL/pgSQL
    function (``pg_schema.py::GET_TEMPORAL_CO_ACCESS_FN``) already
    filters both endpoints to ``access_count >= min_access`` server-side;
    this function does not re-filter, it only groups. "Recurring" here
    means "both endpoints have been individually revisited >= threshold
    times AND were accessed close together in the same window" — the
    function returns one row per (last_accessed) snapshot, not a
    multi-window repeat count, so this is a proxy for recurrence via
    access_count, not a literal repeated-pairing count. Documented
    precisely to avoid overclaiming what the SQL measures.
    Postcondition: components with >= ``min_cluster_size`` members,
    sorted by (size, avg proximity) descending, each capped at
    ``_MAX_MEMORY_IDS_PER_DOSSIER`` members (highest-proximity edges'
    endpoints kept first); at most ``max_dossiers`` returned.
    """
    if not pairs:
        return []
    uf = _UnionFind()
    weight_sum: dict[int, float] = {}
    weight_count: dict[int, float] = {}
    for a, b, _w in pairs:
        uf.union(a, b)
    # Sort edges by proximity descending so the truncation below keeps the
    # strongest-linked members first within an oversized component.
    ordered_edges = sorted(pairs, key=lambda p: p[2], reverse=True)
    members: dict[int, list[int]] = {}
    for a, b, w in ordered_edges:
        root = uf.find(a)
        bucket = members.setdefault(root, [])
        for node in (a, b):
            if node not in bucket:
                bucket.append(node)
        weight_sum[root] = weight_sum.get(root, 0.0) + w
        weight_count[root] = weight_count.get(root, 0.0) + 1

    heat_by_id = heat_by_id or {}
    components = [ids for ids in members.values() if len(ids) >= min_cluster_size]
    components.sort(
        key=lambda ids: (len(ids), weight_sum.get(uf.find(ids[0]), 0.0)), reverse=True
    )

    dossiers: list[DistillDossier] = []
    for ids in components[:max_dossiers]:
        capped = ids[:_MAX_MEMORY_IDS_PER_DOSSIER]
        avg_heat = (
            sum(heat_by_id.get(i, 0.0) for i in capped) / len(capped) if capped else 0.0
        )
        dossiers.append(
            DistillDossier(
                kind="co_access_family",
                topic="",  # filled by the handler from fetched content
                domain="",
                memory_ids=capped,
                avg_heat=avg_heat,
            )
        )
    return dossiers


def dossier_from_cluster(cluster: "CurationCluster") -> DistillDossier:
    """Adapt an ``auto_curator.CurationCluster`` into a ``DistillDossier``.

    Precondition: ``cluster`` was produced by
    ``core.auto_curator.build_clusters`` (entity-cohesive grouping,
    already tested and tuned — MIN_MEMORIES_PER_CLUSTER,
    MIN_AVG_HEAT_FOR_PAGE — reused as-is rather than re-implementing
    entity clustering a second time in this module).
    Postcondition: ``memory_ids`` is capped at
    ``_MAX_MEMORY_IDS_PER_DOSSIER`` — ``build_clusters`` itself does not
    bound cluster size (only its downstream wiki-authoring prompt does,
    via ``MAX_MEMORIES_PER_PROMPT`` — a different, unrelated cap this
    module cannot rely on). Found live on the dev-DB dry-run (INC7.8
    verdict measurement): one real entity_family cluster had 53 members
    before this cap.
    """
    capped_ids = list(cluster.memory_ids)[:_MAX_MEMORY_IDS_PER_DOSSIER]
    return DistillDossier(
        kind="entity_family",
        topic=cluster.topic,
        domain=cluster.domain,
        memory_ids=capped_ids,
        entities=list(cluster.entities),
        avg_heat=cluster.avg_heat,
    )


# Prompt generation (build_distill_prompt) and the memify_derive usage
# snapshot (summarize_derived_usage) live in distillation_reporting.py —
# split to respect the 300-line file cap (§4.1).
