"""``wiki.citations`` seed-campaign pass (M-D7, INC7.7).

Composition root — wires ``core.wiki_citation_seed`` (pure decision) to
infrastructure (``pg_store_wiki_citation_seed``'s candidate scan,
``pg_store_wiki``'s ``insert_citation`` write). Mirrors
``memory_reheat_pass.py``'s split (I6-D5 precedent): pure decision in
core, I/O in infrastructure, wiring here.

History (M-D7/INC7.7, 2026-07-11): first ran as a one-shot campaign via
``scripts/wiki_citation_seed.py`` — INC6.8/Q5 had explicitly rejected an
*automatic* retroactive backfill for the wiki's pre-existing pages
unless the provenance was not fabricated, so the campaign's dry-run
artifact was reviewed by the user before ``--apply`` (commit
``a434f5bd`` seed, ``f8bcb9e0`` APPLY journal — 20 HIGH-reliability
pairs). That one-shot decision is now settled history, not an open
question.

G-2 grooming (2026-07-11): wired into ``run_wiki_maintenance`` as a
RECURRING reconciliation pass, alongside the campaign script (which
still exists for ad-hoc manual runs). This is a distinct decision from
the one INC6.8/Q5 made, not a reversal of it: the classification logic
(``classify_seed_candidates``) is unchanged — it still inserts ONLY
HIGH-reliability, FK-verified ``(page_id, memory_id)`` pairs, the exact
same non-fabricated-provenance rule the campaign was reviewed against.
What changed is *when* it runs: going forward, new ``wiki.pages`` rows
can get their citation row lost to ``wiki_write``'s best-effort
``_sync_page_and_cite`` degrading silently on a transient failure (its
own documented no-op-on-exception contract) — this pass is the
reconciliation sweep for exactly that class of accidental gap, not a
new retroactive-fabrication decision. Idempotent (measured: 0 ``seeded``
on immediate re-run) and cheap (measured ~15-49ms against a 20-row
candidate set, dev DB, 2026-07-11) — see ``DEFAULT_SEED_SCAN_LIMIT``
for the per-cycle cap.
"""

from __future__ import annotations

import logging
from typing import Any
from mcp_server.core.wiki_citation_seed import (
    SeedCandidate,
    SeedReliability,
    classify_seed_candidates,
)
from mcp_server.infrastructure.pg_store_wiki import insert_citation
from mcp_server.infrastructure.pg_store_wiki_citation_seed import (
    list_existing_page_memory_citations,
    list_page_memory_seed_candidates,
)

logger = logging.getLogger(__name__)

DEFAULT_SEED_SCAN_LIMIT = 5000


def _to_candidates(rows: list[dict]) -> list[Any]:

    return [
        SeedCandidate(
            page_id=row["page_id"],
            memory_id=row["memory_id"],
            domain=row["domain"] or "",
            reliability=SeedReliability.HIGH_DIRECT_MEMORY_ID,
        )
        for row in rows
    ]


async def run_wiki_citation_seed_pass(
    store: Any,
    *,
    apply: bool = False,
    limit: int = DEFAULT_SEED_SCAN_LIMIT,
) -> dict[str, Any]:
    """Seed ``wiki.citations`` from ``wiki.pages.memory_id`` (HIGH tier only).

    Pre-condition:  ``store`` exposes ``batch_pool``
                    (``psycopg_pool.ConnectionPool``), matching
                    ``memory_reheat_pass``/``memory_domain_backfill_
                    pass``'s convention for maintenance sweeps.
    Post-condition: for every ``wiki.pages`` row with ``memory_id IS
                    NOT NULL`` (``list_page_memory_seed_candidates``,
                    up to ``limit`` rows): classified via
                    ``core.wiki_citation_seed.classify_seed_candidates``
                    against the existing-citations snapshot; if
                    ``apply`` is True and the decision is ``"insert"``,
                    ``insert_citation(conn, page_id, session_id="",
                    domain=candidate.domain, memory_id=candidate.
                    memory_id)`` is called — its own ``ON CONFLICT DO
                    NOTHING`` on ``uq_wiki_citations_page_memory`` is
                    the final dedup authority, so a race between scan
                    and write degrades to a counted ``skipped_race``,
                    never a duplicate row or a crash. ``apply=False``
                    performs the identical scan and classification
                    without writing (dry run) — ``seeded``/
                    ``already_cited``/``journal`` are identical either
                    way except for the missing DB round-trip, so a
                    caller can diff dry-run vs. applied output to
                    confirm 1:1 correspondence (mirrors
                    ``memory_reheat_pass``'s dry-run contract). Re-
                    running after ``--apply`` finds every seeded pair
                    now in ``existing_pairs``, so ``seeded`` is 0 on
                    immediate re-run (idempotence).
    """

    out: dict[str, Any] = {
        "scanned_rows": 0,
        "seeded": 0,
        "already_cited": 0,
        "skipped_race": 0,
        "journal": [],
        "status": "ok",
    }
    try:
        with store.batch_pool.connection() as conn:
            rows = list_page_memory_seed_candidates(conn, limit)
            out["scanned_rows"] = len(rows)
            candidates = _to_candidates(rows)
            page_ids = [c.page_id for c in candidates]
            existing_pairs = list_existing_page_memory_citations(conn, page_ids)
            decisions = classify_seed_candidates(candidates, existing_pairs)

            for decision in decisions:
                c = decision.candidate
                if decision.action == "skip_existing":
                    out["already_cited"] += 1
                    continue

                new_id = None
                if apply:
                    new_id = insert_citation(
                        conn,
                        page_id=c.page_id,
                        session_id="",
                        domain=c.domain,
                        memory_id=c.memory_id,
                    )
                    if new_id is None:
                        out["skipped_race"] += 1
                        continue

                out["seeded"] += 1
                out["journal"].append(
                    {
                        "page_id": c.page_id,
                        "memory_id": c.memory_id,
                        "domain": c.domain,
                        "reliability": c.reliability.value,
                        "outcome": "seeded" if apply else "would_seed",
                    }
                )
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("wiki_citation_seed_pass failed (non-fatal): %s", exc)
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    return out


__all__ = ["DEFAULT_SEED_SCAN_LIMIT", "run_wiki_citation_seed_pass"]
