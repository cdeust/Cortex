"""Wiki Phase 4 — Thermodynamic consolidation sweep.

Runs three passes over wiki.pages:

Modes:
  full sweep:   wiki_consolidate({})
  dry-run:      wiki_consolidate({"dry_run": true})
  partial:      wiki_consolidate({"limit": 500})
  skip stale:   wiki_consolidate({"skip_staleness": true})

Composition root only — wires core/wiki_thermodynamics + core/
wiki_staleness against pg_store_wiki + filesystem.

source: ADR-0455"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.core.wiki_thermodynamics import evaluate_page, summarise
from mcp_server.handlers.wiki_consolidate_staleness import run_staleness_pass
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.pg_store_wiki import (
    apply_thermo_decisions,
    insert_memo,
    list_pages_for_decay,
)


schema = {
    "description": (
        "Run the periodic wiki maintenance sweep: thermodynamic heat decay, "
        "lifecycle transitions (active → area → archived, archived → active "
        "on revival), and staleness checks for pages whose file references "
        "no longer exist on disk. Phase 4 of the wiki redesign pipeline; "
        "schedule on a daily/weekly cadence. Mutates wiki.pages, wiki.page_sources "
        "(link_kind='references') and writes audit memos. Distinct from "
        "`consolidate` (which operates on memories, not wiki pages), and from "
        "`wiki_purge` (which deletes pages failing classifier rules). "
        "File-existence checks are sandboxed to repo_root. Latency ~1-3s for "
        "5000 pages. Returns {pages_evaluated, pages_decayed, transitions, "
        "staleness (includes references_written), avg_heat_before/after}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "limit": {
                "type": "integer",
                "description": (
                    "Max pages to evaluate in this sweep. Pages are processed "
                    "oldest-touched first."
                ),
                "default": 5000,
                "minimum": 1,
                "maximum": 50000,
                "examples": [500, 5000, 20000],
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "Compute decay/transition/staleness decisions and return "
                    "the summary without persisting any changes."
                ),
                "default": False,
                "examples": [False, True],
            },
            "skip_staleness": {
                "type": "boolean",
                "description": (
                    "Skip Pass 2 (filesystem reference checks). Useful when "
                    "running consolidation in an environment without the "
                    "source tree mounted."
                ),
                "default": False,
                "examples": [False, True],
            },
            "include_archived": {
                "type": "boolean",
                "description": (
                    "Also evaluate already-archived pages — only useful to "
                    "detect revivals from new citations; usually handled by "
                    "the citation trigger automatically."
                ),
                "default": False,
                "examples": [False, True],
            },
            "repo_root": {
                "type": "string",
                "description": (
                    "Absolute path used as the sandbox root when resolving "
                    "page file references for staleness checks. Defaults to "
                    "the current working directory."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


def _run_decay_pass(
    conn: Any, pages: list[dict], now: datetime, *, dry_run: bool
) -> tuple[Any, int]:
    """Pass 1: heat decay + lifecycle transitions.

    Returns ``(thermo_stats, pages_updated)``.
    """
    original_heats = {p["id"]: float(p.get("heat") or 0.0) for p in pages}
    decisions = [evaluate_page(p, now=now) for p in pages]
    stats = summarise(decisions, original_heats)

    pages_updated = 0
    if not dry_run:
        pages_updated = apply_thermo_decisions(conn, decisions)
        # Memo only the transitions, not every pure decay
        for d in decisions:
            if d.transitioned:
                insert_memo(
                    conn,
                    subject_type="page",
                    subject_id=d.page_id,
                    decision=f"transition_{d.new_lifecycle}",
                    rationale=d.rationale,
                    inputs={"new_heat": round(d.new_heat, 4)},
                    confidence=0.9,
                    author="thermo",
                )
    return stats, pages_updated


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    limit = int(args.get("limit", 5000))
    dry_run = bool(args.get("dry_run", False))
    skip_staleness = bool(args.get("skip_staleness", False))
    include_archived = bool(args.get("include_archived", False))
    repo_root_arg = args.get("repo_root")
    repo_root = Path(repo_root_arg) if repo_root_arg else Path.cwd()

    store = _get_store()
    conn = store._conn
    now = datetime.now(tz=timezone.utc)

    pages = list_pages_for_decay(conn, limit=limit, include_archived=include_archived)
    if not pages:
        return {
            "pages_evaluated": 0,
            "note": "no eligible pages (no active/area pages exist)",
        }

    stats, pages_updated = _run_decay_pass(conn, pages, now, dry_run=dry_run)

    stale_summary: dict[str, Any] = {"skipped": True}
    if not skip_staleness:
        stale_summary = run_staleness_pass(
            conn, pages, repo_root=repo_root, dry_run=dry_run
        )

    if not dry_run:
        conn.commit()

    return {
        "pages_evaluated": stats.pages_evaluated,
        "pages_decayed": stats.pages_decayed,
        "pages_updated": pages_updated,
        "transitions": stats.transitions,
        "heat_floor_count": stats.heat_floor_count,
        "avg_heat_before": round(stats.avg_heat_before, 4),
        "avg_heat_after": round(stats.avg_heat_after, 4),
        "staleness": stale_summary,
        "dry_run": dry_run,
        "wiki_root": str(WIKI_ROOT),
    }
