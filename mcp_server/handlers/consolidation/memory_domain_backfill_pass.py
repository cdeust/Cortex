"""Backfill pass: re-derive and persist the domain for memories stuck
with an empty ``domain`` column (I6-D3).

Composition root — wires ``core.memory_domain_backfill`` (pure
priority-order derivation) to infrastructure (DB reads/writes via
``pg_store_memory_domain``) and to the two production domain-resolution
functions ``remember`` and ``backfill_memories`` already use for the
exact same evidence (``resolve_cwd`` for ``directory_context``,
``slug_to_domain`` for ``project:<slug>`` tags) — no new resolution
logic, only a retrospective re-application of the existing write-time
logic to rows it never ran against successfully.

source: ADR-0367"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.memory_domain_backfill import (
    ResolveDirectoryFn,
    ResolveProjectTagFn,
    derive_memory_domain,
)
from mcp_server.shared.domain_mapping import resolve_cwd
from mcp_server.handlers.backfill_helpers import slug_to_domain
from mcp_server.infrastructure.pg_store_memory_domain import (
    tag_memory_orphan,
    update_memory_domain,
    list_domainless_memories,
)

logger = logging.getLogger(__name__)

# source: ADR-0367
DEFAULT_MEMORY_DOMAIN_BACKFILL_LIMIT = 5000


def _default_resolve_directory() -> ResolveDirectoryFn:

    return resolve_cwd


def _default_resolve_project_tag() -> ResolveProjectTagFn:

    return slug_to_domain


def _process_memory(
    conn: Any,
    row: dict[str, Any],
    resolve_directory: ResolveDirectoryFn,
    resolve_project_tag: ResolveProjectTagFn,
    *,
    apply: bool,
    out: dict[str, Any],
) -> None:
    """Derive one memory's domain and persist the outcome (fill or orphan-tag)."""

    memory_id = row["id"]
    directory_context = row.get("directory_context") or ""
    tags = row.get("tags") or []

    derivation = derive_memory_domain(
        directory_context, tags, resolve_directory, resolve_project_tag
    )

    if derivation.domain:
        out["by_evidence"][derivation.evidence] = (
            out["by_evidence"].get(derivation.evidence, 0) + 1
        )
        out["journal"].append(
            {
                "id": memory_id,
                "evidence": derivation.evidence,
                "domain": derivation.domain,
            }
        )
        if apply:
            update_memory_domain(conn, memory_id, derivation.domain)
    else:
        out["orphaned"] += 1
        out["journal"].append({"id": memory_id, "evidence": "", "domain": ""})
        if apply:
            tag_memory_orphan(conn, memory_id)


async def run_memory_domain_backfill_pass(
    store: Any,
    *,
    apply: bool = False,
    limit: int = DEFAULT_MEMORY_DOMAIN_BACKFILL_LIMIT,
    include_orphans: bool = False,
    resolve_directory: ResolveDirectoryFn | None = None,
    resolve_project_tag: ResolveProjectTagFn | None = None,
) -> dict[str, Any]:
    """Re-derive and persist the domain for domain-less memories.

    source: ADR-0367"""

    resolve_directory = resolve_directory or _default_resolve_directory()
    resolve_project_tag = resolve_project_tag or _default_resolve_project_tag()

    out: dict[str, Any] = {
        "scanned": 0,
        "filled": 0,
        "orphaned": 0,
        "by_evidence": {},
        "journal": [],
        "status": "ok",
    }
    try:
        with store.batch_pool.connection() as conn:
            rows = list_domainless_memories(
                conn, limit, include_orphans=include_orphans
            )
            out["scanned"] = len(rows)
            for row in rows:
                _process_memory(
                    conn,
                    row,
                    resolve_directory,
                    resolve_project_tag,
                    apply=apply,
                    out=out,
                )
        out["filled"] = sum(out["by_evidence"].values())
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("memory_domain_backfill_pass failed (non-fatal): %s", exc)
        out["status"] = f"error: {type(exc).__name__}: {exc}"
    return out


__all__ = ["DEFAULT_MEMORY_DOMAIN_BACKFILL_LIMIT", "run_memory_domain_backfill_pass"]
