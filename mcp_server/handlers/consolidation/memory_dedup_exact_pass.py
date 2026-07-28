"""Dedup pass: collapse groups of byte-identical active memories onto
their hottest member via supersession (I6-D1, INC6.3).

Composition root — wires ``core.memory_dedup_exact`` (pure survivor
election) to infrastructure (``pg_store_memory_dedup``'s group scan and
CAS supersede-to-existing write). Mirrors
``memory_domain_backfill_pass.py``'s split (I6-D3 precedent): pure
decision in core, I/O in infrastructure, wiring here.

One-shot campaign pass, not wired into ``consolidate``: the write-path
dedup gate (``core/curation.py``) already prevents new exact duplicates
going forward (I6 audit) — this pass drains the pre-existing stock.
Invoked by ``scripts/memory_dedup_exact.py``.
"""

from __future__ import annotations

import logging
from itertools import groupby
from typing import Any

from mcp_server.core.memory_dedup_exact import DuplicateMember, elect_survivor
from mcp_server.infrastructure.pg_store_memory_dedup import (
    supersede_to_existing,
    list_exact_duplicate_groups,
)

logger = logging.getLogger(__name__)

# Mirrors pg_store_memory_dedup.DEFAULT_DEDUP_SCAN_LIMIT — kept as a
# separate re-export point so callers of this handler don't need to
# reach into the infrastructure module for the default.
DEFAULT_DEDUP_SCAN_LIMIT = 5000


def _rows_to_groups(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split the flat, ``dup_key``-ordered row list back into per-group lists.

    Pre-condition:  ``rows`` is ordered by ``dup_key`` (guaranteed by
                    ``list_exact_duplicate_groups``'s ``ORDER BY``).
    Post-condition: returns one list per distinct ``dup_key``, each with
                    >= 2 members (the SQL's own ``HAVING COUNT(*) > 1``
                    already enforces this — ``groupby`` here only
                    re-partitions, it cannot merge or drop rows).
    """
    return [
        list(members) for _key, members in groupby(rows, key=lambda r: r["dup_key"])
    ]


def _process_group(
    conn: Any,
    group: list[dict[str, Any]],
    *,
    apply: bool,
    out: dict[str, Any],
) -> None:
    """Elect one group's survivor and supersede the rest, journaling both."""

    members = [
        DuplicateMember(
            id=row["id"],
            effective_heat=row["effective_heat"],
            created_at=row["created_at"],
        )
        for row in group
    ]
    election = elect_survivor(members)
    domains = sorted({row["domain"] or "" for row in group})

    superseded_written: list[int] = []
    for duplicate_id in election.superseded_ids:
        written = False
        if apply:
            written = supersede_to_existing(conn, duplicate_id, election.survivor_id)
        if apply and not written:
            out["skipped_race"] += 1
        else:
            superseded_written.append(duplicate_id)

    out["groups"] += 1
    out["superseded_total"] += len(superseded_written)
    out["journal"].append(
        {
            "dup_key": group[0]["dup_key"],
            "survivor_id": election.survivor_id,
            "superseded_ids": superseded_written,
            "group_size": len(group),
            "domains": domains,
        }
    )


async def run_memory_dedup_exact_pass(
    store: Any,
    *,
    apply: bool = False,
    limit: int = DEFAULT_DEDUP_SCAN_LIMIT,
) -> dict[str, Any]:
    """Collapse every active exact-duplicate group onto its hottest member.

    Pre-condition:  ``store`` exposes ``batch_pool``
                    (``psycopg_pool.ConnectionPool``), matching how
                    ``consolidate`` and ``memory_domain_backfill_pass``
                    already borrow connections for maintenance sweeps.
    Post-condition: for every scanned group of >= 2 active exact
                    duplicates (``current_memories WHERE NOT is_stale``,
                    grouped by normalized-content md5 — I6-D1's key),
                    the member elected by
                    ``core.memory_dedup_exact.elect_survivor`` (highest
                    ``effective_heat``, tie-broken by earliest
                    ``created_at``) is left untouched; every other member
                    has ``superseded_by_id`` set to the survivor's id IFF
                    ``apply`` is True. ``apply=False`` performs the same
                    scan and election without writing (dry run) — the
                    returned counts and journal are identical either way,
                    so a caller can diff dry-run vs. applied output to
                    confirm 1:1 correspondence (mirrors
                    ``memory_domain_backfill_pass``'s dry-run contract).
                    ``superseded_total`` is the number of edges actually
                    written (or, in dry-run, the number that WOULD be
                    written); a race that concurrently supersedes a
                    survivor between scan and write is counted in
                    ``skipped_race`` and excluded from
                    ``superseded_total`` and the journal's
                    ``superseded_ids`` (never silently dropped — logged
                    for the caller to re-run). Never mutates content,
                    tags, or domain on any row (I6-D1: "sans toucher au
                    contenu"); ``journal[*].domains`` records the DISTINCT
                    domains observed across the group for the campaign
                    report only — it is not written back anywhere.
    """

    out: dict[str, Any] = {
        "scanned_rows": 0,
        "groups": 0,
        "superseded_total": 0,
        "skipped_race": 0,
        "journal": [],
        "status": "ok",
    }
    try:
        with store.batch_pool.connection() as conn:
            rows = list_exact_duplicate_groups(conn, limit)
            out["scanned_rows"] = len(rows)
            for group in _rows_to_groups(rows):
                _process_group(conn, group, apply=apply, out=out)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("memory_dedup_exact_pass failed (non-fatal): %s", exc)
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    return out


__all__ = ["DEFAULT_DEDUP_SCAN_LIMIT", "run_memory_dedup_exact_pass"]
