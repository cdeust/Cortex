"""Wiki Phase 4, Pass 2 — staleness brake + reference-link persistence.

source: ADR-0456"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.core.wiki_staleness import (
    StalenessDecision,
    evaluate_staleness,
    harvest_page_refs_typed,
    normalize_typed_refs,
)
from mcp_server.infrastructure.pg_store_wiki import (
    apply_staleness_decisions,
    get_claim_file_refs_for_pages,
    insert_memo,
)
from mcp_server.infrastructure.pg_store_wiki_sources import upsert_page_sources


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


def _persist_reference_links(
    conn: Any, pages: list[dict], per_page_typed_refs: dict[int, dict[str, str]]
) -> int:
    """Persist harvested file refs as ``link_kind='references'`` rows.

        Returns the total number of rows written across all pages.

    source: ADR-0456"""
    written = 0
    for p in pages:
        normalized = normalize_typed_refs(per_page_typed_refs[p["id"]])
        entries = sorted(normalized.items())
        written += upsert_page_sources(conn, p["id"], entries, link_kind="references")
    return written


def _harvest_all_pages(
    conn: Any, pages: list[dict]
) -> tuple[dict[int, dict[str, str]], dict[int, list[str]], set[str]]:
    """Harvest typed refs for every page; return (typed, plain, all-refs-union).

    source: ADR-0456"""
    claim_refs_by_page = get_claim_file_refs_for_pages(conn, [p["id"] for p in pages])
    per_page_typed: dict[int, dict[str, str]] = {}
    per_page_plain: dict[int, list[str]] = {}
    all_refs: set[str] = set()
    for p in pages:
        typed = harvest_page_refs_typed(p, claim_refs_by_page.get(p["id"], []))
        per_page_typed[p["id"]] = typed
        refs = sorted(typed)
        per_page_plain[p["id"]] = refs
        all_refs.update(refs)
    return per_page_typed, per_page_plain, all_refs


def _memo_staleness_transitions(
    conn: Any, stale_decisions: list[StalenessDecision]
) -> None:
    """Audit-trail memo for each staleness transition (set or cleared)."""
    for d in stale_decisions:
        if not d.transitioned:
            continue
        insert_memo(
            conn,
            subject_type="page",
            subject_id=d.page_id,
            decision="staleness_set" if d.is_stale_now else "staleness_cleared",
            rationale=d.rationale,
            inputs={"missing": d.missing_refs[:10], "total_refs": len(d.file_refs)},
            confidence=0.8,
            author="staleness",
        )


def run_staleness_pass(
    conn: Any,
    pages: list[dict],
    *,
    repo_root: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Evaluate staleness for ``pages`` and, if not ``dry_run``, persist it.

        Returns the ``staleness`` summary dict for the handler's response.

    source: ADR-0456"""
    per_page_typed_refs, per_page_refs, all_refs = _harvest_all_pages(conn, pages)
    existence = _check_existence(all_refs, repo_root)

    stale_decisions: list[StalenessDecision] = [
        evaluate_staleness(
            page_id=p["id"],
            is_stale_was=bool(p.get("is_stale", False)),
            file_refs=per_page_refs[p["id"]],
            existence=existence,
        )
        for p in pages
    ]

    stale_written = 0
    references_written = 0
    if not dry_run:
        stale_written = apply_staleness_decisions(conn, stale_decisions)
        _memo_staleness_transitions(conn, stale_decisions)
        references_written = _persist_reference_links(conn, pages, per_page_typed_refs)

    return {
        "pages_with_refs": sum(1 for d in stale_decisions if d.file_refs),
        "pages_now_stale": sum(1 for d in stale_decisions if d.is_stale_now),
        "transitions_written": stale_written,
        "references_written": references_written,
        "files_checked": len(existence),
        "files_missing": sum(1 for v in existence.values() if not v),
        "skipped": False,
    }


__all__ = ["run_staleness_pass"]
