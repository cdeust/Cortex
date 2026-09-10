"""``wiki.citations`` seed-campaign pass (M-D7, INC7.7).

source: ADR-0377"""

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

    source: ADR-0377"""

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
