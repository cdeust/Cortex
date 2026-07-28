"""Near-duplicate calibration + treatment passes (I6-D2, INC6.4 campaign).

Two composition roots, wiring ``core.near_dup_calibration`` (pure
stratification/threshold/component logic) to infrastructure
(``pg_store_near_dup``'s candidate scan, ``pg_store_memory_dedup``'s
reused CAS supersede-to-existing write):

  - ``run_near_dup_sample``: measure the candidate-pair distribution and
    produce a deterministic stratified sample with contents, for manual
    (LLM-judged) labeling. Writes nothing.
  - ``run_near_dup_apply_pass``: given an ALREADY-CALIBRATED threshold S
    (the caller supplies it — this module never selects S itself, that
    is ``core.near_dup_calibration.select_threshold``'s job on labeled
    data), group pairs >= S into components and supersede each
    component onto its elected survivor (reusing
    ``core.memory_dedup_exact.elect_survivor`` and
    ``pg_store_memory_dedup.supersede_to_existing`` — Q2 arbitration:
    the auto-collapse mechanism is IDENTICAL to I6-D1's, only the
    candidate-selection query differs). Pairs in
    ``[min_similarity, threshold)`` are NEVER superseded — they are
    written to a review-queue artifact only (Q2: no auto-collapse below
    the measured-100%-precision boundary).

One-shot campaign passes, not wired into ``consolidate`` — mirrors
``memory_dedup_exact_pass.py``'s standalone-campaign framing.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.memory_dedup_exact import DuplicateMember, elect_survivor
from mcp_server.core.near_dup_calibration import (
    CandidatePair,
    build_components,
    stratified_sample,
)
from mcp_server.core.near_dup_calibration import bucket_by_stratum
from mcp_server.infrastructure.pg_store_near_dup import (
    fetch_contents,
    list_candidate_pairs,
    fetch_member_stats,
)
from mcp_server.infrastructure.pg_store_memory_dedup import supersede_to_existing

logger = logging.getLogger(__name__)

DEFAULT_PER_STRATUM = 20

# source: structural — a near-duplicate component is at least a pair
_MIN_COMPONENT_MEMBERS = 2


async def run_near_dup_sample(
    store: Any,
    *,
    top_k: int = 30,
    min_similarity: float = 0.75,
    per_stratum: int = DEFAULT_PER_STRATUM,
    anchor_limit: int = 20000,
) -> dict[str, Any]:
    """Scan candidate pairs, stratify, deterministically sample, fetch contents.

    Pre-condition:  ``store`` exposes ``batch_pool``
                    (``psycopg_pool.ConnectionPool``).
    Post-condition: ``result["candidate_total"]`` is the total number of
                    distinct candidate pairs found at/above
                    ``min_similarity`` (the measured distribution's
                    denominator); ``result["histogram"]`` maps each
                    stratum label to its candidate count (I6-D2 step 2's
                    histogram); ``result["sample"]`` is a list of dicts
                    (``id_a``, ``id_b``, ``similarity``, ``content_a``,
                    ``content_b``) — the deterministic stratified sample
                    (``core.near_dup_calibration.stratified_sample``),
                    up to ``per_stratum`` pairs per stratum, WITH
                    contents fetched for manual labeling. Writes nothing
                    to the DB — read-only measurement pass.
    """

    out: dict[str, Any] = {
        "candidate_total": 0,
        "histogram": {},
        "sample": [],
        "status": "ok",
    }
    try:
        with store.batch_pool.connection() as conn:
            pairs = list_candidate_pairs(
                conn,
                top_k=top_k,
                min_similarity=min_similarity,
                anchor_limit=anchor_limit,
            )
            out["candidate_total"] = len(pairs)
            buckets = bucket_by_stratum(pairs)
            out["histogram"] = {
                label: len(members) for label, members in buckets.items()
            }

            sample = stratified_sample(pairs, per_stratum=per_stratum)
            ids: set[int] = set()
            for pair in sample:
                ids.add(pair.id_a)
                ids.add(pair.id_b)
            contents = fetch_contents(conn, sorted(ids))

            out["sample"] = [
                {
                    "id_a": pair.id_a,
                    "id_b": pair.id_b,
                    "similarity": pair.similarity,
                    "content_a": contents.get(pair.id_a, ""),
                    "content_b": contents.get(pair.id_b, ""),
                }
                for pair in sample
            ]
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("near_dup sample scan failed (non-fatal): %s", exc)
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    return out


def _elect_and_journal_component(
    conn: Any,
    member_ids: frozenset[int],
    stats: dict[int, dict],
    *,
    apply: bool,
    out: dict[str, Any],
) -> None:
    """Elect one component's survivor and supersede the rest, journaling both."""

    # Members superseded concurrently between the pair scan and this
    # write have no stats row (fetch_member_stats only returns ids still
    # present in current_memories) — drop them; a component that
    # collapses to < 2 present members after this filter has nothing
    # left to supersede.
    members = [
        DuplicateMember(
            id=mid,
            effective_heat=stats[mid]["effective_heat"],
            created_at=stats[mid]["created_at"],
        )
        for mid in member_ids
        if mid in stats
    ]
    if len(members) < _MIN_COMPONENT_MEMBERS:
        out["skipped_vanished"] += len(member_ids) - len(members)
        return

    election = elect_survivor(members)
    superseded_written: list[int] = []
    for duplicate_id in election.superseded_ids:
        written = False
        if apply:
            written = supersede_to_existing(conn, duplicate_id, election.survivor_id)
        if apply and not written:
            out["skipped_race"] += 1
        else:
            superseded_written.append(duplicate_id)

    out["components"] += 1
    out["superseded_total"] += len(superseded_written)
    out["journal"].append(
        {
            "survivor_id": election.survivor_id,
            "superseded_ids": superseded_written,
            "component_size": len(members),
        }
    )


async def run_near_dup_apply_pass(
    store: Any,
    *,
    threshold: float,
    apply: bool = False,
    top_k: int = 30,
    min_similarity: float = 0.75,
    anchor_limit: int = 20000,
) -> dict[str, Any]:
    """Auto-supersede components >= ``threshold``; review-queue the rest.

    Pre-condition:  ``threshold`` is a CALIBRATED value (the output of
                    ``core.near_dup_calibration.select_threshold`` on a
                    labeled sample) — this function does not calibrate,
                    it only applies. ``threshold >= min_similarity``.
    Post-condition: every candidate pair with ``similarity >= threshold``
                    is grouped into a connected component
                    (``core.near_dup_calibration.build_components``);
                    each component elects a survivor (highest
                    ``effective_heat``, tie-broken by earliest
                    ``created_at`` — identical contract to I6-D1's exact
                    dedup) and every other member is superseded onto it
                    IFF ``apply`` is True (``apply=False`` performs the
                    same scan/election without writing — dry run, same
                    contract as ``memory_dedup_exact_pass``).
                    ``result["superseded_total"]`` counts edges
                    written (or that would be written, in dry-run).
                    Every candidate pair with
                    ``min_similarity <= similarity < threshold`` is
                    NEVER superseded — it is listed verbatim (with
                    contents) in ``result["review_queue"]`` (Q2: file de
                    revue, no auto-collapse below the measured boundary).
    """

    out: dict[str, Any] = {
        "candidate_total": 0,
        "components": 0,
        "superseded_total": 0,
        "skipped_race": 0,
        "skipped_vanished": 0,
        "journal": [],
        "review_queue": [],
        "status": "ok",
    }
    try:
        with store.batch_pool.connection() as conn:
            pairs = list_candidate_pairs(
                conn,
                top_k=top_k,
                min_similarity=min_similarity,
                anchor_limit=anchor_limit,
            )
            out["candidate_total"] = len(pairs)

            above: list[CandidatePair] = [p for p in pairs if p.similarity >= threshold]
            below: list[CandidatePair] = [p for p in pairs if p.similarity < threshold]

            if above:
                components = build_components(above)
                all_ids = sorted({mid for comp in components for mid in comp})
                stats = fetch_member_stats(conn, all_ids)
                for comp in components:
                    _elect_and_journal_component(
                        conn, comp, stats, apply=apply, out=out
                    )

            if below:
                review_ids = sorted({p.id_a for p in below} | {p.id_b for p in below})
                contents = fetch_contents(conn, review_ids)
                out["review_queue"] = [
                    {
                        "id_a": p.id_a,
                        "id_b": p.id_b,
                        "similarity": p.similarity,
                        "content_a": contents.get(p.id_a, ""),
                        "content_b": contents.get(p.id_b, ""),
                    }
                    for p in below
                ]
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("near_dup apply pass failed (non-fatal): %s", exc)
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    return out


__all__ = [
    "DEFAULT_PER_STRATUM",
    "run_near_dup_sample",
    "run_near_dup_apply_pass",
]
