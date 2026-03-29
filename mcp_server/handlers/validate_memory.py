"""Handler: validate_memory — assess and flag stale memories.

Scans memories for file references that no longer exist on disk.
Updates is_stale flag in-place. Can target a single memory, a domain,
a directory, or all memories.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp_server.core.staleness import assess_staleness, collect_all_refs
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": "Validate memories against current filesystem state. Marks stale memories whose referenced files no longer exist.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "Validate a single memory by ID",
            },
            "domain": {
                "type": "string",
                "description": "Validate all memories for a domain",
            },
            "directory": {
                "type": "string",
                "description": "Validate all memories for a directory context",
            },
            "base_dir": {
                "type": "string",
                "description": "Base directory for resolving relative paths (defaults to cwd)",
            },
            "staleness_threshold": {
                "type": "number",
                "description": "Score 0-1 above which a memory is marked stale (default 0.5)",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, assess but do not update database. Default false.",
            },
        },
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Path resolution ───────────────────────────────────────────────────────


def _resolve_existing_paths(refs: list[str], base_dir: str) -> set[str]:
    """Return the subset of refs that exist on the filesystem.

    Tries each ref as-is, relative to base_dir, and with progressive
    path stripping to handle sandbox/host path mismatches.
    """
    existing: set[str] = set()
    base = Path(base_dir).expanduser() if base_dir else Path.cwd()

    for ref in refs:
        if _path_exists(ref, base):
            existing.add(ref)

    return existing


def _path_exists(ref: str, base: Path) -> bool:
    """Check if a path ref exists via multiple resolution strategies."""
    p = Path(ref)
    # Exact absolute match
    if p.is_absolute() and p.exists():
        return True
    # Relative to base_dir
    if (base / p).exists():
        return True
    # Progressive stripping (e.g. /sandbox/project/src/a.py -> src/a.py)
    parts = p.parts
    for i in range(1, len(parts)):
        if (base / Path(*parts[i:])).exists():
            return True
    return False


# ── Memory selection ─────────────────────────────────────────────────────


def _select_memories(args: dict, store: MemoryStore) -> list[dict]:
    """Determine which memories to validate based on args."""
    if args.get("memory_id") is not None:
        mem = store.get_memory(int(args["memory_id"]))
        return [mem] if mem else []

    if args.get("domain"):
        return store.get_memories_for_domain(args["domain"], min_heat=0.0, limit=500)

    if args.get("directory"):
        return store.get_memories_for_directory(args["directory"], min_heat=0.0)

    return store.get_all_memories_for_validation(limit=1000)


# ── Assessment ───────────────────────────────────────────────────────────


def _assess_memories(
    memories: list[dict],
    existing_paths: set[str],
    threshold: float,
) -> tuple[list[dict], list[int]]:
    """Assess each memory for staleness. Returns reports and stale IDs."""
    reports = []
    stale_ids: list[int] = []

    for mem in memories:
        report = assess_staleness(
            memory_id=mem["id"],
            content=mem.get("content", ""),
            existing_paths=existing_paths,
            threshold=threshold,
        )
        reports.append(
            {
                "memory_id": report.memory_id,
                "total_refs": report.total_refs,
                "missing_refs": report.missing_refs,
                "changed_refs": report.changed_refs,
                "staleness_score": report.staleness_score,
                "is_stale": report.is_stale,
                "reason": report.reason,
            }
        )
        if report.is_stale:
            stale_ids.append(report.memory_id)

    return reports, stale_ids


# ── Handler ───────────────────────────────────────────────────────────────


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate memory or memories against current filesystem state."""
    args = args or {}
    base_dir = args.get("base_dir", "") or os.getcwd()
    threshold = float(args.get("staleness_threshold", 0.5))
    dry_run = args.get("dry_run", False)

    store = _get_store()
    memories = _select_memories(args, store)

    if not memories:
        return {"validated": 0, "stale_found": 0, "stale_updated": 0, "reports": []}

    all_refs = collect_all_refs(memories)
    existing_paths = _resolve_existing_paths(all_refs, base_dir)
    reports, stale_ids = _assess_memories(memories, existing_paths, threshold)

    updated = 0
    if not dry_run:
        for mid in stale_ids:
            store.mark_memory_stale(mid, stale=True)
            updated += 1

    return {
        "validated": len(memories),
        "stale_found": len(stale_ids),
        "stale_updated": updated,
        "dry_run": dry_run,
        "reports": reports,
    }
