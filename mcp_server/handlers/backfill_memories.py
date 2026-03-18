"""Handler: backfill_memories -- auto-import prior conversations into memory.

Scans ~/.claude/projects/ JSONL conversation files, extracts memorable
items, and stores them with backfill tags. Idempotent via file-hash
tracking in a backfill_log table.

See backfill_helpers.py for discovery, hashing, and concept-linking logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.core.session_extractor import extract_memorable_items
from mcp_server.handlers.backfill_helpers import (
    discover_files,
    ensure_backfill_log,
    file_hash,
    find_concepts,
    is_already_backfilled,
    link_concepts,
    mark_backfilled,
    slug_to_domain,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.scanner import read_head_tail

# -- Schema --

schema = {
    "description": (
        "Auto-import prior Claude Code conversations into the memory store. "
        "Idempotent -- tracks already-processed session files by hash. "
        "Links historical work to core concepts automatically."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Filter to a specific project directory slug (e.g. '-Users-you-myproject'). Default: all projects.",
            },
            "max_files": {
                "type": "integer",
                "description": "Maximum number of JSONL files to process per call (default 20).",
            },
            "min_importance": {
                "type": "number",
                "description": "Minimum importance for extracted items (default 0.35).",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview what would be imported without storing (default false).",
            },
            "force_reprocess": {
                "type": "boolean",
                "description": "Re-process files even if already backfilled (default false).",
            },
        },
    },
}


def _parse_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Extract and validate handler arguments."""
    args = args or {}
    return {
        "project_filter": args.get("project", ""),
        "max_files": int(args.get("max_files", 20)),
        "min_importance": float(args.get("min_importance", 0.35)),
        "dry_run": bool(args.get("dry_run", False)),
        "force_reprocess": bool(args.get("force_reprocess", False)),
    }


async def _import_single_item(
    store: MemoryStore,
    item: dict,
    cwd: str,
    domain: str,
    project_slug: str,
) -> int | None:
    """Store one extracted item. Returns memory_id if stored, else None."""
    from mcp_server.handlers.remember import handler as remember_handler

    content = item.get("content", "")
    if not content or len(content) < 20:
        return None

    tags = item.get("tags", []) + ["_backfill", f"project:{project_slug[:30]}"]
    result = await remember_handler(
        {
            "content": content,
            "tags": tags,
            "directory": cwd,
            "domain": domain,
            "source": f"backfill:{project_slug[:40]}",
            "force": True,
        }
    )

    if not result.get("stored"):
        return None
    return result.get("memory_id")


async def _import_file(
    store: MemoryStore,
    path: Path,
    project_slug: str,
    min_importance: float,
) -> tuple[int, int]:
    """Import one JSONL file. Returns (imported, skipped)."""
    from mcp_server.core.session_extractor import extract_session_summary

    try:
        records = read_head_tail(path, head=200, tail=200)
    except Exception:
        return 0, 0

    if not records:
        return 0, 0

    summary = extract_session_summary(records)
    items = extract_memorable_items(records, min_importance=min_importance)
    if not items:
        return 0, 0

    cwd = summary.get("cwd", "")
    domain = slug_to_domain(project_slug)

    imported = 0
    for item in items:
        mid = await _import_single_item(store, item, cwd, domain, project_slug)
        if mid is not None:
            imported += 1
            concepts = find_concepts(item.get("content", ""))
            if concepts:
                link_concepts(store, mid, concepts)

    return imported, len(items) - imported


def _build_dry_run_preview(
    path: Path,
    slug: str,
    min_importance: float,
) -> dict | None:
    """Build a preview entry for dry-run mode. Returns None on error."""
    try:
        records = read_head_tail(path, head=100, tail=100)
        items = extract_memorable_items(records, min_importance=min_importance)
        return {
            "file": path.name,
            "project": slug,
            "extractable_items": len(items),
            "concepts": list(
                {c for item in items for c in find_concepts(item.get("content", ""))}
            ),
        }
    except Exception:
        return None


def _filter_candidates(
    store: MemoryStore,
    candidates: list[tuple[Path, str]],
    max_files: int,
    force_reprocess: bool,
) -> tuple[list[tuple[Path, str, str]], int]:
    """Filter candidates by hash, returning (path, slug, hash) and skip count."""
    ready: list[tuple[Path, str, str]] = []
    skipped = 0
    for path, slug in candidates[:max_files]:
        try:
            fhash = file_hash(path)
        except OSError:
            continue
        if not force_reprocess and is_already_backfilled(store, path, fhash):
            skipped += 1
            continue
        ready.append((path, slug, fhash))
    return ready, skipped


async def _process_dry_run(
    ready: list[tuple[Path, str, str]],
    min_importance: float,
    total_candidates: int,
    files_skipped: int,
) -> dict[str, Any]:
    """Build dry-run preview from filtered candidates."""
    preview: list[dict] = []
    total_items = 0
    for path, slug, _ in ready:
        entry = _build_dry_run_preview(path, slug, min_importance)
        if entry:
            preview.append(entry)
            total_items += entry["extractable_items"]
    return {
        "dry_run": True,
        "files_found": total_candidates,
        "already_processed": files_skipped,
        "would_import": total_items,
        "preview": preview[:10],
    }


async def _process_imports(
    store: MemoryStore,
    ready: list[tuple[Path, str, str]],
    min_importance: float,
    total_candidates: int,
    files_skipped: int,
) -> dict[str, Any]:
    """Import files and return result summary."""
    total_imported = 0
    total_skipped = 0
    files_processed = 0
    for path, slug, fhash in ready:
        imported, skipped = await _import_file(store, path, slug, min_importance)
        if imported > 0 or skipped == 0:
            mark_backfilled(store, path, fhash, imported)
            files_processed += 1
            total_imported += imported
            total_skipped += skipped
    return {
        "backfilled": total_imported,
        "files_processed": files_processed,
        "files_already_done": files_skipped,
        "items_gated": total_skipped,
        "concept_links_created": 0,
        "total_files_found": total_candidates,
    }


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Backfill prior conversations into the memory store."""
    parsed = _parse_args(args)
    settings = get_memory_settings()
    store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    ensure_backfill_log(store)

    candidates = discover_files(parsed["project_filter"], parsed["max_files"])
    if not candidates:
        return {
            "backfilled": 0,
            "skipped_files": 0,
            "already_processed": 0,
            "error": "no_session_files_found",
        }

    ready, files_skipped = _filter_candidates(
        store,
        candidates,
        parsed["max_files"],
        parsed["force_reprocess"],
    )

    if parsed["dry_run"]:
        return await _process_dry_run(
            ready,
            parsed["min_importance"],
            len(candidates),
            files_skipped,
        )

    return await _process_imports(
        store,
        ready,
        parsed["min_importance"],
        len(candidates),
        files_skipped,
    )
