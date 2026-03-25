"""Handler: seed_project -- bootstrap memory from an existing codebase.

Performs structural analysis of a project directory and stores key
discoveries as memories.

Stages:
  1. Config extraction   -- package.json, pyproject.toml, Cargo.toml, go.mod, etc.
  2. Docs harvesting     -- README, CLAUDE.md, docs/, ADRs, changelogs
  3. Entry point scan    -- main.py, index.js, cmd/, bin/, __main__.py
  4. CI/CD detection     -- .github/workflows, Makefile, Dockerfile, tox.ini
  5. Structural summary  -- top-level layout, language detection, module map

Each stage stores discoveries via the remember handler (respects write gate).
Returns a summary of what was seeded.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.handlers.seed_project_stages import (
    collect_all_discoveries,
    heat_for_tags,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# -- Schema --

schema = {
    "description": "Bootstrap memory from an existing codebase. Analyzes structure, config, docs, entry points, and CI/CD. Stores key discoveries as memories.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Root directory of the codebase (defaults to cwd)",
            },
            "domain": {
                "type": "string",
                "description": "Domain to tag seeded memories with (auto-detected if omitted)",
            },
            "max_file_size_kb": {
                "type": "integer",
                "description": "Skip files larger than this (default 64 KB)",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, report discoveries without storing. Default false.",
            },
        },
    },
}


def _parse_args(args: dict[str, Any] | None) -> tuple[Path, str, int, bool]:
    """Extract and validate handler arguments."""
    args = args or {}
    directory = args.get("directory", "") or os.getcwd()
    domain = args.get("domain", "")
    max_kb = int(args.get("max_file_size_kb", 64))
    dry_run = args.get("dry_run", False)
    return Path(directory).expanduser().resolve(), domain, max_kb * 1024, dry_run


async def _store_discoveries(
    discoveries: list[dict],
    root: Path,
    domain: str,
) -> tuple[int, int, list[int]]:
    """Store discoveries via remember handler. Returns (stored, skipped, ids)."""
    stored = 0
    skipped = 0
    memory_ids: list[int] = []
    store = _get_store()

    for disc in discoveries:
        disc_tags = disc.get("tags", []) + ["seeded"]
        initial_heat = heat_for_tags(disc_tags)
        result = await remember_handler(
            {
                "content": disc["content"],
                "tags": disc_tags,
                "directory": str(root),
                "domain": domain,
                "source": "seed_project",
                "force": True,
            }
        )
        if result.get("stored"):
            stored += 1
            mid = result.get("memory_id")
            if mid:
                memory_ids.append(mid)
                store._conn.execute(
                    "UPDATE memories SET heat = %s WHERE id = %s",
                    (initial_heat, mid),
                )
        else:
            skipped += 1

    if stored:
        store._conn.commit()

    return stored, skipped, memory_ids


def _build_stage_counts(discoveries: list[dict]) -> dict[str, int]:
    """Count discoveries per stage from tags."""
    return {
        "structural_summary": 1,
        "configs": sum(1 for d in discoveries if "config" in d.get("tags", [])),
        "docs": sum(1 for d in discoveries if "documentation" in d.get("tags", [])),
        "entry_points": sum(
            1 for d in discoveries if "entry-point" in d.get("tags", [])
        ),
        "cicd": sum(1 for d in discoveries if "ci-cd" in d.get("tags", [])),
    }


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Seed memory from an existing codebase."""
    root, domain, max_bytes, dry_run = _parse_args(args)

    if not root.exists() or not root.is_dir():
        return {"seeded": False, "reason": f"directory not found: {root}"}

    purged = 0
    if not dry_run:
        purged = _get_store().delete_memories_by_tag("seeded")

    all_discoveries = collect_all_discoveries(root, max_bytes)

    if dry_run:
        return {
            "seeded": False,
            "dry_run": True,
            "discoveries": len(all_discoveries),
            "titles": [d["title"] for d in all_discoveries],
        }

    stored, skipped, memory_ids = await _store_discoveries(
        all_discoveries,
        root,
        domain,
    )

    return {
        "seeded": True,
        "directory": str(root),
        "domain": domain,
        "discoveries": len(all_discoveries),
        "stored": stored,
        "skipped": skipped,
        "purged_stale": purged,
        "memory_ids": memory_ids,
        "stages": _build_stage_counts(all_discoveries),
    }
