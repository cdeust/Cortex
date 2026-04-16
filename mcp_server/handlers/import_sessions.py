"""Handler: import_sessions — import conversation history into memory store.

Scans JSONL conversation files from ~/.claude/projects/ and extracts
memorable content (decisions, errors, architecture notes, insights).
Stores via the remember handler's full pipeline (thermodynamics, write gate,
knowledge graph, engram allocation).

Supports:
  - Full import: all projects
  - Project filter: specific project directory
  - Domain filter: specific domain
  - Dry run: preview what would be imported without storing

latency_class: long_running

Memory discipline: this handler ONLY reads JSONL files via the streaming
head+tail path (``read_head_tail`` in scanner.py). No whole-file accumulator
list exists. See ADR-0045 R2 ("no ingestion path reads a whole file/store
into Python memory"); the former ``full_read=True`` branch was removed in
v3.13.0 Phase 1 because it materialised entire multi-GB JSONLs in a Python
list before extraction, producing an OOM path that Taleb's audit flagged as
a black-swan failure mode on large histories.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from mcp_server.core.session_extractor import (
    extract_memorable_items,
    extract_session_summary,
)
from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.infrastructure.scanner import read_head_tail

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": (
        "Import Claude Code conversation history from ~/.claude/projects/ "
        "into the memory store. Walks JSONL session files, extracts "
        "memorable items (decisions, errors-and-fixes, architecture notes, "
        "key insights) via session_extractor, and routes each through the "
        "`remember` write gate (thermodynamics, hierarchical predictive "
        "coding, knowledge graph, engram allocation). Supports project / "
        "domain filtering and dry-run preview. Use this for an initial "
        "bootstrap or to ingest sessions from another machine. Distinct "
        "from `backfill_memories` (preferred for incremental, hash-tracked "
        "re-runs over the same source), `seed_project` (codebase "
        "structure), and `codebase_analyze` (source files). Mutates "
        "memories + entities + relationships tables. Latency varies "
        "(~1-30min depending on history size). Returns "
        "{sessions_processed, memories_imported, dry_run, errors}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "project": {
                "type": "string",
                "description": (
                    "Filter to a single Claude Code project directory slug. "
                    "Omit to import from every project."
                ),
                "examples": ["-Users-alice-code-cortex"],
            },
            "domain": {
                "type": "string",
                "description": "Restrict import to sessions classified under this cognitive domain.",
                "examples": ["cortex", "ai-architect"],
            },
            "min_importance": {
                "type": "number",
                "description": (
                    "Minimum importance (0.0-1.0) for an extracted item to be "
                    "imported. Lower = more memories, more noise."
                ),
                "default": 0.4,
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.3, 0.4, 0.6],
            },
            "max_sessions": {
                "type": "integer",
                "description": "Maximum number of session files to process this call.",
                "minimum": 1,
                "examples": [50, 200],
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "Preview what would be imported without writing to the store. "
                    "Always run a dry_run first."
                ),
                "default": False,
            },
        },
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────


def _discover_jsonl_files(
    project_filter: str,
) -> list[tuple[Path, str]]:
    """Find all JSONL conversation files, optionally filtered by project."""
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.exists():
        return []

    results: list[tuple[Path, str]] = []

    for pdir in sorted(projects_dir.iterdir()):
        if not pdir.is_dir():
            continue
        if project_filter and pdir.name != project_filter:
            continue

        for f in sorted(pdir.iterdir()):
            if not f.is_file() or not f.name.endswith(".jsonl"):
                continue
            if "subagent" in f.name or "subagents" in str(f):
                continue
            results.append((f, pdir.name))

    return results


def _read_session_records(file_path: Path) -> list[dict]:
    """Read JSONL records via streaming head+tail only.

    precondition: ``file_path`` points to a (possibly multi-GB) JSONL file.
    postcondition: returns a bounded list of parsed dict records whose total
    on-disk span is ≤ HEAD_BYTES + TAIL_BYTES (~40 KB) regardless of file
    size; the function never materialises the whole file in memory.

    Source: ADR-0045 R2 — no ingestion path reads a whole file/store into
    Python memory. The previous ``full_read`` branch was deleted in v3.13.0
    Phase 1.
    """
    return read_head_tail(file_path)


def _detect_domain_from_path(cwd: str) -> str:
    """Extract a domain label from a working directory path."""
    if not cwd:
        return "unknown"

    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part.lower() in ("developments", "projects", "repos", "src", "code"):
            if i + 1 < len(parts):
                return parts[i + 1].lower()

    return parts[-1].lower() if parts else "unknown"


async def _store_memory(
    item: dict[str, Any],
    project: str,
    domain: str,
) -> bool:
    """Store a single extracted item via the remember handler."""
    from mcp_server.handlers.backfill_helpers import (
        age_decayed_heat,
        compute_age_days,
    )
    from mcp_server.handlers.remember import handler as remember_handler

    remember_args = {
        "content": item["content"],
        "tags": item["tags"],
        "domain": domain,
        "source": "import",
        "force": False,
    }
    # Preserve original session timestamp AND compute age-decayed initial
    # heat from it, so historical conversations don't form a bimodal cohort
    # at heat=1.0 after import. Source: issue #14 P1.
    timestamp = item.get("timestamp")
    if timestamp:
        remember_args["created_at"] = str(timestamp)
        age_days = compute_age_days(str(timestamp))
        remember_args["initial_heat"] = age_decayed_heat(age_days)
    result = await remember_handler(remember_args)

    return bool(result and result.get("stored"))


def _build_preview_item(
    item: dict[str, Any],
    project_name: str,
    domain: str,
) -> dict[str, Any]:
    """Build a truncated preview dict for dry-run mode."""
    content = item["content"]
    return {
        "content": content[:120] + ("..." if len(content) > 120 else ""),
        "tags": item["tags"],
        "importance": round(item["importance"], 3),
        "project": project_name,
        "domain": domain,
    }


async def _process_session_items(
    items: list[dict[str, Any]],
    project_name: str,
    session_domain: str,
    dry_run: bool,
    preview_items: list[dict],
) -> tuple[int, int]:
    """Process items from one session. Returns (imported, gated) counts."""
    imported = 0
    gated = 0
    for item in items:
        if dry_run:
            preview_items.append(
                _build_preview_item(item, project_name, session_domain),
            )
            imported += 1
        else:
            stored = await _store_memory(item, project_name, session_domain)
            if stored:
                imported += 1
            else:
                gated += 1
    return imported, gated


def _build_result(
    total_imported: int,
    total_gated: int,
    total_skipped: int,
    sessions_scanned: int,
    total_files: int,
    dry_run: bool,
    preview_items: list[dict],
    errors: list[str],
) -> dict[str, Any]:
    """Assemble the final result dict."""
    result: dict[str, Any] = {
        "imported": total_imported,
        "gated": total_gated,
        "skipped": total_skipped,
        "sessions_scanned": sessions_scanned,
        "total_files": total_files,
        "dry_run": dry_run,
    }
    if dry_run and preview_items:
        result["preview"] = preview_items[:50]
        result["preview_truncated"] = len(preview_items) > 50
    if errors:
        result["errors"] = errors[:10]
    return result


# ── Handler ───────────────────────────────────────────────────────────────


async def _process_single_file(
    file_path: Path,
    project_name: str,
    domain_filter: str,
    min_importance: float,
    dry_run: bool,
    preview_items: list[dict],
) -> tuple[int, int, int, bool]:
    """Process one JSONL file. Returns (imported, gated, skipped, scanned)."""
    records = _read_session_records(file_path)
    if not records:
        return 0, 0, 0, False

    summary = extract_session_summary(records)
    items = extract_memorable_items(records, min_importance=min_importance)
    if not items:
        return 0, 0, 0, True

    session_domain = _detect_domain_from_path(summary.get("cwd", ""))
    if domain_filter and session_domain != domain_filter:
        return 0, 0, len(items), True

    imported, gated = await _process_session_items(
        items,
        project_name,
        session_domain,
        dry_run,
        preview_items,
    )
    return imported, gated, 0, True


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Import conversation sessions into the memory store."""
    args = args or {}
    project_filter = args.get("project", "")
    domain_filter = args.get("domain", "")
    min_importance = args.get("min_importance", 0.4)
    max_sessions = args.get("max_sessions", 0)
    dry_run = args.get("dry_run", False)

    jsonl_files = _discover_jsonl_files(project_filter)
    if not jsonl_files:
        return {"imported": 0, "sessions_scanned": 0, "error": "no_sessions_found"}

    if max_sessions > 0:
        jsonl_files = jsonl_files[:max_sessions]

    total_imported = total_skipped = total_gated = sessions_scanned = 0
    preview_items: list[dict] = []
    errors: list[str] = []

    for file_path, project_name in jsonl_files:
        try:
            imported, gated, skipped, scanned = await _process_single_file(
                file_path,
                project_name,
                domain_filter,
                min_importance,
                dry_run,
                preview_items,
            )
            total_imported += imported
            total_gated += gated
            total_skipped += skipped
            sessions_scanned += int(scanned)
        except Exception as e:
            errors.append(f"{file_path.name}: {e}")
            print(
                f"[import_sessions] Error processing {file_path.name}: {e}",
                file=sys.stderr,
            )

    return _build_result(
        total_imported,
        total_gated,
        total_skipped,
        sessions_scanned,
        len(jsonl_files),
        dry_run,
        preview_items,
        errors,
    )
