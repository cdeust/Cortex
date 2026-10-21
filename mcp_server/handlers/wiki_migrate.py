"""Wiki filesystem → DB migration + ghost reconciliation (Phase 1.2 of
redesign, extended for FS<->PG parity).

Re-running is safe — body_hash guards against redundant upsert writes;
the purge phase re-computes ghosts from scratch every run (no state to
go stale).

source: ADR-0463"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp_server.shared.wiki_pages import parse_page
from mcp_server.core.wiki_templates import STATUS_VALUES
from mcp_server.handlers._tool_meta import DESTRUCTIVE
from mcp_server.infrastructure.pg_store_wiki import body_hash
from mcp_server.infrastructure.wiki_mirror_apply import apply_wiki_mirror
from mcp_server.infrastructure.wiki_pages_listing import list_pages
from mcp_server.infrastructure.wiki_store import read_page
from mcp_server.shared.wiki_source_paths import extract_document_paths
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store

# Wiki-link syntax: [[slug]] or [[slug|display text]]
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# source: ADR-0463
_DOMAIN_PATH_PARTS = 3

# wiki.pages.status's DB CHECK constraint (pg_schema.py) accepts the union
# of: the digital-garden maturity vocabulary ('seedling'/'budding'/
# 'evergreen', the column default) plus 'living' (emitted by
# core/auto_curator.py:475,538 and handlers/consolidation/page_io.py:376)
# plus every kind-specific ADR/specs status in STATUS_VALUES
# (core/wiki_templates.py). Frontmatter is FS-authored and not itself  # noqa: ERA001
# constrained, so any value outside this union must be caught here — the
# system boundary (coding-standards.md 3.2) — before it reaches the DB.
_LEGACY_MATURITY_STATUSES = frozenset({"seedling", "budding", "evergreen", "living"})
_VALID_STATUS_VALUES = _LEGACY_MATURITY_STATUSES | {
    v for values in STATUS_VALUES.values() for v in values
}


def _normalize_status(raw_status: str, rel_path: str) -> tuple[str, str | None]:
    """Validate a frontmatter status against wiki.pages' DB CHECK union.

    Precondition: raw_status is a non-empty string (the caller has already
    collapsed missing frontmatter status/maturity to 'seedling').
    Postcondition: returns (raw_status, None) when raw_status is a member
    of _VALID_STATUS_VALUES; otherwise returns ('seedling', <warning>) —
    'seedling' matches the column's own DB default, so an unrecognized
    frontmatter value can never trip pages_status_check.
    """
    if raw_status in _VALID_STATUS_VALUES:
        return raw_status, None
    warning = f"{rel_path}: unknown status '{raw_status}' -> falling back to 'seedling'"
    return "seedling", warning


# ── MCP schema ───────────────────────────────────────────────────────────

schema = {
    "title": "Wiki — migrate FS to PG + reconcile ghosts",
    "annotations": DESTRUCTIVE,
    "description": (
        "One-shot idempotent sync of the filesystem wiki "
        "(~/.claude/methodology/wiki/) into wiki.pages / wiki.links / "
        "wiki.page_sources. Walks every PAGE_KINDS directory, upserts "
        "each page keyed on rel_path (body_hash guards no-op re-writes), "
        "re-resolves [[slug]] links, then reconciles: any wiki.pages row "
        "whose rel_path no longer exists on disk (deleted file, rename, "
        "or a wiki_purge run — which only touches the FS, never PG) is "
        "purged from wiki.pages, cascading via FK ON DELETE CASCADE to "
        "wiki.links and wiki.page_sources. The `_`-prefixed kind dirs "
        "(_kinds/_rules/_views/_bibliography/_dashboards) and the root "
        "README.md are outside the scan entirely on both phases, so they "
        "are never upserted and never purged. Defaults to dry_run=true "
        "(report the ghost rel_paths without deleting); pass "
        "dry_run=false to actually purge. Distinct from `wiki_purge` "
        "(deletes FS files that fail the classifier, never touches PG) — "
        "this tool never touches the FS, only reconciles PG to match it. "
        "A frontmatter status outside wiki.pages' DB CHECK union falls "
        "back to 'seedling' and is reported in warnings (never blocks "
        "the page write). Returns {pages_processed, pages_written, "
        "pages_unchanged, links_written, links_resolved_pass3, "
        "purge: {dry_run, ghost_count, ghost_paths, purged}, errors, "
        "error_count, warnings, warning_count}."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "dry_run": {
                "type": "boolean",
                "default": True,
                "description": (
                    "If true (default), report which wiki.pages rows "
                    "would be purged as filesystem ghosts without "
                    "deleting them. Pass false to actually delete."
                ),
            },
        },
    },
}


def _slug_from_rel_path(rel_path: str) -> str:
    """Extract the slug portion from a rel_path like ``adr/cortex/42-foo.md``.

    The slug is the filename stem minus the optional ``<id>-`` prefix.
    """
    stem = Path(rel_path).stem
    m = re.match(r"^\d+-(.+)$", stem)
    return m.group(1) if m else stem


def _extract_body_sections(body: str) -> tuple[str, dict[str, str]]:
    """Split a body into (lead, sections_by_heading).

    Lead = text before the first ``## `` heading.
    Sections = ``## H2`` headings → body text.
    """
    parts = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    lead = parts[0].strip()
    sections: dict[str, str] = {}
    # parts alternates: [lead, heading1, body1, heading2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        heading = parts[i].strip()
        section_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[heading] = section_body
    # Clean lead of any leading H1
    lead = re.sub(r"^#\s+.+?\n", "", lead, count=1).strip()
    return lead, sections


def page_row_from_md(
    rel_path: str, content: str, memory_id: int | None = None
) -> dict[str, Any]:
    """Build an upsert_page payload from a parsed markdown file.

    source: ADR-0463"""
    doc = parse_page(content)
    fm = doc.frontmatter or {}
    body = doc.body or ""
    lead, sections = _extract_body_sections(body)
    slug = _slug_from_rel_path(rel_path)

    # Kind is the top-level folder (singular form stored in frontmatter
    # may differ from the directory name — prefer frontmatter if present)
    path_kind = rel_path.split("/", 1)[0] if "/" in rel_path else ""
    kind = fm.get("kind") or path_kind.rstrip("s")

    # Domain is the second path component
    parts = rel_path.split("/")
    has_domain_component = len(parts) >= _DOMAIN_PATH_PARTS
    domain = fm.get("domain") or (parts[1] if has_domain_component else "_general")

    raw_tags = fm.get("tags", [])
    if isinstance(raw_tags, str):
        tags = [raw_tags]
    elif isinstance(raw_tags, list):
        tags = [str(t) for t in raw_tags]
    else:
        tags = []

    # source: ADR-0463
    documents = extract_document_paths(fm, tags)

    raw_status = str(fm.get("status") or fm.get("maturity") or "seedling")
    status, status_warning = _normalize_status(raw_status, rel_path)

    return {
        "memory_id": memory_id,
        "rel_path": rel_path,
        "slug": slug,
        "kind": kind,
        "title": fm.get("title") or slug,
        "domain": domain,
        "domains": [domain] if domain else [],
        "tags": tags,
        "audience": fm.get("audience", []),
        "requires": fm.get("requires", []),
        "status": status,
        # Not a DB column — upsert_page only reads the params it names, so
        # this rides along on the row dict and is popped by
        # _upsert_all_pages before/after the insert to build the run's
        # warnings list (never written to wiki.pages).
        "status_warning": status_warning,
        "lifecycle_state": fm.get("lifecycle_state", "active"),
        "supersedes": fm.get("supersedes"),
        "superseded_by": fm.get("superseded_by"),
        "verified": fm.get("verified"),
        "lead": lead,
        "sections": sections,
        "body": body,
        "body_hash": body_hash(body),
        "documents": documents,
        "documents_primary": documents[0] if documents else None,
    }


def _extract_wikilinks(body: str) -> list[str]:
    """Return the list of [[slug]] targets found in a body."""
    return _WIKILINK_RE.findall(body)


def _memory_id_from_rel_path(rel_path: str) -> int | None:
    """If the filename starts with ``<int>-``, return that int. Else None."""
    stem = Path(rel_path).stem
    m = re.match(r"^(\d+)-", stem)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _parse_pages(
    root: Path, rel_paths: list[str]
) -> tuple[list[dict], dict[str, list[str]], list[str], list[str]]:
    """Read and parse every page (no connection held): the upsert payloads,
    each page's [[slug]] targets, read errors and status warnings."""
    pages: list[dict] = []
    links: dict[str, list[str]] = {}
    errors: list[str] = []
    warnings: list[str] = []
    for rp in rel_paths:
        try:
            content = read_page(root, rp)
            if content is None:
                continue
            mid = _memory_id_from_rel_path(rp)
            row = page_row_from_md(rp, content, memory_id=mid)
            status_warning = row.pop("status_warning", None)
            if status_warning:
                warnings.append(status_warning)
            pages.append({"rel_path": rp, "row": row, "memory_id": mid})
            targets = _extract_wikilinks(parse_page(content).body or "")
            if targets:
                links[rp] = sorted(set(targets))
        except Exception as e:  # noqa: BLE001 — per-page batch isolation — failure is reported in the returned errors list
            errors.append(f"{rp}: {e}")
    return pages, links, errors, warnings


def migrate_wiki(wiki_root: Path | str, store: Any, *, dry_run: bool = True) -> dict:
    """Mirror every wiki .md into wiki.pages + wiki.links, then reconcile
    ghosts: pages are read and parsed here, then one store operation runs
    the four passes (``wiki_mirror_apply.apply_wiki_mirror``) and rolls a
    dry run back. Stale memory ids from filenames are dropped there.

    source: ADR-0463"""
    root = Path(wiki_root)
    rel_paths = list_pages(root)
    pages, links, read_errors, warnings = _parse_pages(root, rel_paths)
    applied = store.call(
        apply_wiki_mirror, pages, links, rel_paths, dry_run, pool="batch"
    )
    errors = read_errors + applied["errors"]
    return {
        "pages_processed": len(rel_paths),
        "pages_written": applied["pages_written"],
        "pages_unchanged": applied["pages_unchanged"],
        "links_written": applied["links_written"],
        "links_resolved_pass3": applied["links_resolved_pass3"],
        "purge": applied["purge"],
        "errors": errors[:10],
        "error_count": len(errors),
        "warnings": warnings[:10],
        "warning_count": len(warnings),
    }


async def handler(args: dict | None = None) -> dict:
    """MCP tool entry: run migration + ghost-page reconciliation, return summary."""

    args = args or {}
    dry_run = bool(args.get("dry_run", True))
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return migrate_wiki(WIKI_ROOT, store, dry_run=dry_run)


__all__ = [
    "handler",
    "schema",
    "migrate_wiki",
]


if __name__ == "__main__":
    # Direct CLI invocation: python -m mcp_server.handlers.wiki_migrate [--dry-run]
    import argparse
    import asyncio
    import json as _json

    parser = argparse.ArgumentParser(
        description="Wiki FS -> PG migration + ghost-page reconciliation"
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Report ghost rel_paths without deleting (default).",
    )
    parser.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Actually purge ghost rel_paths from wiki.pages.",
    )
    cli_args = parser.parse_args()

    print(
        _json.dumps(
            asyncio.run(handler({"dry_run": cli_args.dry_run})),
            indent=2,
        )
    )
