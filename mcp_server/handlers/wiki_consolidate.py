"""Wiki Phase 4 — Thermodynamic consolidation sweep.

Runs three passes over wiki.pages:

  1. Heat decay + lifecycle transitions (active → area → archived,
     archived → active on revival).
  2. Staleness brake — pages whose file references no longer exist
     get is_stale=True; pages whose refs all came back get
     is_stale=False (auto-recovery).
  3. Memo every transition for the audit trail.

Modes:
  full sweep:   wiki_consolidate({})
  dry-run:      wiki_consolidate({"dry_run": true})
  partial:      wiki_consolidate({"limit": 500})
  skip stale:   wiki_consolidate({"skip_staleness": true})

Composition root only — wires core/wiki_thermodynamics + core/
wiki_staleness against pg_store_wiki + filesystem.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.core.wiki_staleness import (
    StalenessDecision,
    evaluate_staleness,
    harvest_page_refs,
)
from mcp_server.core.wiki_thermodynamics import evaluate_page, summarise
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    apply_staleness_decisions,
    apply_thermo_decisions,
    get_claim_file_refs_for_pages,
    insert_memo,
    list_pages_for_decay,
)


schema = {
    "description": (
        "Run the periodic wiki maintenance sweep: thermodynamic heat decay, "
        "lifecycle transitions (active → area → archived, archived → active "
        "on revival), and staleness checks for pages whose file references "
        "no longer exist on disk. Phase 4 of the wiki redesign pipeline; "
        "schedule on a daily/weekly cadence. Mutates wiki.pages and writes "
        "audit memos. Distinct from `consolidate` (which operates on "
        "memories, not wiki pages), and from `wiki_purge` (which deletes "
        "pages failing classifier rules). File-existence checks are sandboxed "
        "to repo_root. Latency ~1-3s for 5000 pages. Returns "
        "{pages_evaluated, pages_decayed, transitions, staleness, "
        "avg_heat_before/after}."
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
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


def _check_existence(refs: set[str], repo_root: Path) -> dict[str, bool]:
    """Resolve each ref against repo_root; return existence map."""
    out: dict[str, bool] = {}
    for ref in refs:
        ref = ref.strip().rstrip(".,;:")
        if not ref:
            continue
        # Reject absolute paths and traversal — staleness checks must
        # not escape the repo root (defence against poisoned page text)
        try:
            p = Path(ref)
            if p.is_absolute():
                out[ref] = False
                continue
            target = (repo_root / p).resolve()
            target.relative_to(repo_root.resolve())
            out[ref] = target.exists()
        except (ValueError, OSError):
            out[ref] = False
    return out


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

    # ── Pass 1: Decay + lifecycle ─────────────────────────────────────
    pages = list_pages_for_decay(conn, limit=limit, include_archived=include_archived)
    if not pages:
        return {
            "pages_evaluated": 0,
            "note": "no eligible pages (no active/area pages exist)",
        }

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

    # ── Pass 2: Staleness ─────────────────────────────────────────────
    stale_summary: dict[str, Any] = {"skipped": True}
    if not skip_staleness:
        page_ids = [p["id"] for p in pages]
        claim_refs_by_page = get_claim_file_refs_for_pages(conn, page_ids)
        # Combine claim refs + inline refs per page
        per_page_refs: dict[int, list[str]] = {}
        all_refs: set[str] = set()
        for p in pages:
            refs = harvest_page_refs(p, claim_refs_by_page.get(p["id"], []))
            per_page_refs[p["id"]] = refs
            all_refs.update(refs)
        existence = _check_existence(all_refs, repo_root)

        stale_decisions: list[StalenessDecision] = []
        for p in pages:
            decision = evaluate_staleness(
                page_id=p["id"],
                is_stale_was=bool(p.get("is_stale", False)),
                file_refs=per_page_refs[p["id"]],
                existence=existence,
            )
            stale_decisions.append(decision)

        stale_written = 0
        if not dry_run:
            stale_written = apply_staleness_decisions(conn, stale_decisions)
            for d in stale_decisions:
                if d.transitioned:
                    insert_memo(
                        conn,
                        subject_type="page",
                        subject_id=d.page_id,
                        decision=(
                            "staleness_set" if d.is_stale_now else "staleness_cleared"
                        ),
                        rationale=d.rationale,
                        inputs={
                            "missing": d.missing_refs[:10],
                            "total_refs": len(d.file_refs),
                        },
                        confidence=0.8,
                        author="staleness",
                    )
        stale_summary = {
            "pages_with_refs": sum(1 for d in stale_decisions if d.file_refs),
            "pages_now_stale": sum(1 for d in stale_decisions if d.is_stale_now),
            "transitions_written": stale_written,
            "files_checked": len(existence),
            "files_missing": sum(1 for v in existence.values() if not v),
            "skipped": False,
        }

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
