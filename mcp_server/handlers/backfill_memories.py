"""Handler: backfill_memories -- auto-import prior conversations into memory.

Scans ~/.claude/projects/ JSONL conversation files, extracts memorable
items, and stores them with backfill tags. Skips a file whose hash is
already in the backfill_log table (unless force_reprocess=True), but
each stored item goes through remember(force=True), which bypasses the
predictive-coding write gate — so a re-run with force_reprocess=True,
or two files that yield overlapping content, can create duplicate
memory rows. The tool is NON_IDEMPOTENT_WRITE overall; only the
file-hash skip is idempotent.

See backfill_helpers.py for discovery, hashing, and concept-linking logic.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp_server.core.session_extractor import (
    extract_memorable_items,
    extract_session_summary,
)
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
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.scanner import read_head_tail
from mcp_server.observability import silent_failure
from mcp_server.handlers._tool_meta import NON_IDEMPOTENT_WRITE
from mcp_server.handlers.backfill_helpers import gist_oversized_content
from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.handlers.wiki_pipeline import handler as _pipeline
from mcp_server.handlers.consolidation.cascade import run_cascade_advancement

logger = logging.getLogger(__name__)

# -- Schema --

schema = {
    "title": "Backfill memories",
    "annotations": NON_IDEMPOTENT_WRITE,
    "description": (
        "Import prior Claude Code conversations from ~/.claude/projects/ "
        "into the memory store. Walks JSONL session transcripts, extracts "
        "memorable items (decisions, lessons, errors-and-fixes) via the "
        "session_extractor, stores them with `backfill` tags via "
        "`remember(force=True)` — which BYPASSES the predictive-coding "
        "write gate, not the standard write path — and links each to the "
        "auto-discovered core concepts of the originating project. "
        "Idempotent only at the file level: hashes tracked in "
        "backfill_log so a plain re-run skips already-processed files. "
        "NOT idempotent overall — `force_reprocess=true` re-imports a "
        "file's items with the gate still bypassed, which can create "
        "duplicate memory rows. Use this on first install, after long "
        "absences, or when migrating "
        "to a new machine. Distinct from `import_sessions` (more granular "
        "control, manual file selection), `seed_project` (codebase "
        "structure, not conversation history), and `codebase_analyze` "
        "(source files, not transcripts). Mutates memories + backfill_log "
        "tables. Latency varies (~30s-10min depending on history size). "
        "Returns {sessions_processed, sessions_skipped, memories_imported, "
        "errors}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "project": {
                "type": "string",
                "description": (
                    "Filter to a specific project directory slug (the "
                    "Claude Code project ID). Omit to process every project."
                ),
                "examples": ["-Users-alice-code-cortex"],
            },
            "max_files": {
                "type": "integer",
                "description": (
                    "Maximum number of JSONL session files to process per call. "
                    "Use a small number for an initial dry run, then raise for "
                    "the full backfill."
                ),
                "default": 20,
                "minimum": 1,
                "maximum": 1000,
                "examples": [5, 20, 200],
            },
            "min_importance": {
                "type": "number",
                "description": (
                    "Minimum extracted-item importance (0.0-1.0) to keep. "
                    "Lower values import more lower-signal memories."
                ),
                "default": 0.35,
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.2, 0.35, 0.6],
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "Preview what would be imported without writing to the "
                    "store. Always run a dry_run first."
                ),
                "default": False,
            },
            "force_reprocess": {
                "type": "boolean",
                "description": (
                    "Re-process files even if their hash is in the backfill log. "
                    "Only set this if you have changed the extractor and want a "
                    "fresh pass."
                ),
                "default": False,
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
        # When true (default), kick off the wiki pipeline after imports
        # so memories → claims → concepts → pages happens automatically.
        # Disable if you want to run the pipeline manually afterwards.
        "run_pipeline": bool(args.get("run_pipeline", True)),
    }


# Minimum content length worth importing as a memory.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_CONTENT_CHARS = 20


async def _import_single_item(
    store: MemoryStore,
    item: dict,
    cwd: str,
    domain: str,
    project_slug: str,
) -> int | None:
    """Store one extracted item. Returns memory_id if stored, else None."""

    content = item.get("content", "")
    if not content or len(content) < _MIN_CONTENT_CHARS:
        return None

    content = gist_oversized_content(content)
    tags = item.get("tags", []) + ["_backfill", f"project:{project_slug[:30]}"]
    remember_args = {
        "content": content,
        "tags": tags,
        "directory": cwd,
        "domain": domain,
        "source": f"backfill:{project_slug[:40]}",
        # M-D2 (7.4): a one-shot bulk import pass over prior conversations.
        "write_class": "mechanical",
        "force": True,
    }
    # Preserve the original session timestamp. insert_memory anchors
    # heat_base_set_at to it (A3 decay clock), so effective_heat() decays the
    # baseline by the memory's real age at READ time — the single canonical
    # age-decay path (pg_schema EFFECTIVE_HEAT_FN). We deliberately do NOT
    # pre-decay initial_heat here: that would double-count the same age (once
    # analytically at insert, once dynamically at read). A3's read-time decay
    # also spreads the import cohort by age, subsuming the original issue #14
    # bimodality fix.
    timestamp = item.get("timestamp")
    if timestamp:
        remember_args["created_at"] = str(timestamp)
    result = await remember_handler(remember_args)

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

    try:
        records = read_head_tail(path)
    except OSError:
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
        records = read_head_tail(path)
        items = extract_memorable_items(records, min_importance=min_importance)
        return {
            "file": path.name,
            "project": slug,
            "extractable_items": len(items),
            "concepts": list(
                {c for item in items for c in find_concepts(item.get("content", ""))}
            ),
        }
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("backfill.preview", exc)
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
    run_pipeline: bool = True,
) -> dict[str, Any]:
    """Import files and optionally run the wiki pipeline end-to-end.

    With ``run_pipeline=True`` (the default), once imports complete we
    invoke handlers.wiki_pipeline which chains extract → resolve →
    emerge → synthesize → curate → compile. This is what makes
    "install and see pages" work on fresh installs (Phase 7 cold-start
    fix); without it, users would have to call each tool manually.
    """
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

    result: dict[str, Any] = {
        "backfilled": total_imported,
        "files_processed": files_processed,
        "files_already_done": files_skipped,
        "items_gated": total_skipped,
        "concept_links_created": 0,
        "total_files_found": total_candidates,
    }

    if run_pipeline and total_imported > 0:
        try:
            pipe = await _pipeline({"limit_per_stage": 1000})
            result["pipeline"] = {
                "claims_inserted": pipe.get("claims_inserted", 0),
                "concepts_inserted": pipe.get("concepts_inserted", 0),
                "drafts_approved": pipe.get("drafts_approved", 0),
                "pages_published": pipe.get("pages_published", 0),
            }
        except Exception as e:
            # Log, don't just record. This clause ran the documented
            # fresh-install path; swallowing the exception into a string
            # meant a backfill that produced zero wiki pages still returned
            # a success-shaped payload with no log line anywhere — the
            # FlashRank silent-failure mode a third time (issue #206).
            logger.error(
                "backfill: wiki pipeline failed after importing %d memories; "
                "no wiki pages were produced: %s",
                total_imported,
                e,
                exc_info=True,
            )
            result["pipeline"] = {"error": str(e)}
    return result


def _advance_cascade(store: MemoryStore, result: dict[str, Any]) -> None:
    """Run cascade advancement after backfill to place imported memories
    in the correct consolidation stage based on their real timestamps.

    Mutates ``result`` in place (adds ``cascade_advanced``). No-op when
    nothing was backfilled; a cascade failure is recorded via
    ``silent_failure`` and never fails the backfill itself.
    """
    if result.get("backfilled", 0) <= 0:
        return
    try:
        cascade = run_cascade_advancement(store)
        result["cascade_advanced"] = cascade.get("advanced", 0)
    except Exception as exc:  # noqa: BLE001 — cascade is optional post-processing
        silent_failure.note("backfill.cascade_advancement", exc)


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Backfill prior conversations into the memory store."""
    parsed = _parse_args(args)
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
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

    result = await _process_imports(
        store,
        ready,
        parsed["min_importance"],
        len(candidates),
        files_skipped,
        run_pipeline=parsed["run_pipeline"],
    )

    _advance_cascade(store, result)

    return result
