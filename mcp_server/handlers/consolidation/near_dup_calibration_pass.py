"""Near-duplicate calibration + treatment passes (I6-D2, INC6.4 campaign).

One-shot campaign passes, not wired into ``consolidate`` — mirrors
``memory_dedup_exact_pass.py``'s standalone-campaign framing.

source: ADR-0370"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.memory_dedup_exact import DuplicateMember
from mcp_server.core.near_dup_grouping import election_order, settle_round
from mcp_server.shared.near_dup_calibration import (
    CandidatePair,
    build_components,
    stratified_sample,
)
from mcp_server.shared.near_dup_calibration import bucket_by_stratum
from mcp_server.infrastructure.pg_store_near_dup import (
    fetch_contents,
    ids_near_to,
    list_candidate_pairs,
    fetch_member_stats,
)
from mcp_server.infrastructure.pg_store_memory_dedup import supersede_to_existing

logger = logging.getLogger(__name__)

DEFAULT_PER_STRATUM = 20

# source: ADR-0370
_MIN_COMPONENT_MEMBERS = 2


async def run_near_dup_sample(
    store: Any,
    *,
    top_k: int = 30,
    min_similarity: float = 0.75,
    per_stratum: int = DEFAULT_PER_STRATUM,
) -> dict[str, Any]:
    """Scan candidate pairs, stratify, deterministically sample, fetch contents.

    source: ADR-0370"""

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


def _supersede_group(
    conn: Any,
    survivor_id: int,
    attached: tuple[int, ...],
    *,
    apply: bool,
    out: dict[str, Any],
) -> None:
    """Supersede one group's members into its survivor, journaling it."""
    written: list[int] = []
    for duplicate_id in attached:
        ok = apply and supersede_to_existing(conn, duplicate_id, survivor_id)
        if apply and not ok:
            out["skipped_race"] += 1
        else:
            written.append(duplicate_id)
    out["components"] += 1
    out["superseded_total"] += len(written)
    out["journal"].append(
        {
            "survivor_id": survivor_id,
            "superseded_ids": written,
            "component_size": 1 + len(attached),
        }
    )


def _group_component(
    conn: Any,
    member_ids: frozenset[int],
    stats: dict[int, dict],
    *,
    threshold: float,
    apply: bool,
    out: dict[str, Any],
) -> None:
    """Split one component into survivor-anchored groups (ADR-0370).

    Each round elects the survivor of the pending members and attaches the
    members whose own similarity to it is >= ``threshold``; the others stay
    pending for the next round. A member reached only through a chain is
    never superseded into a survivor it does not duplicate."""
    members = [
        DuplicateMember(
            id=mid,
            effective_heat=stats[mid]["effective_heat"],
            created_at=stats[mid]["created_at"],
        )
        for mid in sorted(member_ids)
        if mid in stats
    ]
    out["skipped_vanished"] += len(member_ids) - len(members)
    pending = election_order(members)
    while len(pending) >= _MIN_COMPONENT_MEMBERS:
        survivor_id = pending[0].id
        others = [m.id for m in pending[1:]]
        near = ids_near_to(conn, survivor_id, others, threshold=threshold)
        attached, pending = settle_round(pending, near)
        if attached:
            _supersede_group(conn, survivor_id, attached, apply=apply, out=out)
        else:
            out["unmerged_total"] += 1
    out["unmerged_total"] += len(pending)


async def run_near_dup_apply_pass(
    store: Any,
    *,
    threshold: float,
    apply: bool = False,
    top_k: int = 30,
    min_similarity: float = 0.75,
) -> dict[str, Any]:
    """Auto-supersede near-duplicates of a survivor; review-queue the rest.

    Pairs >= ``threshold`` are grouped into components, and each component
    into survivor-anchored groups: a member is superseded only into a
    survivor whose own similarity to it is >= ``threshold``. Members left
    alone are counted in ``unmerged_total`` and stay as they are.

    source: ADR-0370"""

    out: dict[str, Any] = {
        "candidate_total": 0,
        "components": 0,
        "superseded_total": 0,
        "skipped_race": 0,
        "skipped_vanished": 0,
        "unmerged_total": 0,
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
            )
            out["candidate_total"] = len(pairs)

            above: list[CandidatePair] = [p for p in pairs if p.similarity >= threshold]
            below: list[CandidatePair] = [p for p in pairs if p.similarity < threshold]

            if above:
                components = build_components(above)
                all_ids = sorted({mid for comp in components for mid in comp})
                stats = fetch_member_stats(conn, all_ids)
                for comp in components:
                    _group_component(
                        conn, comp, stats, threshold=threshold, apply=apply, out=out
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
