"""Helpers for codebase_analyze — file walking, hashing, entity persistence.

Extracted from codebase_analyze.py to keep each file under 300 lines
and each function under 40 lines.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp_server.core.codebase_parser import EXT_TO_LANG, FileAnalysis
from mcp_server.handlers.seed_project_constants import IGNORE_DIRS
from mcp_server.infrastructure.memory_store import MemoryStore

CODEBASE_AGENT_CONTEXT = "codebase"
FILE_TAG_PREFIX = "file:"
HASH_TAG_PREFIX = "hash:"


def _log(msg: str) -> None:
    print(f"[codebase-analyze] {msg}", file=sys.stderr)


# ── File walking ──────────────────────────────────────────────────────────


def collect_source_files(
    root: Path,
    languages: list[str] | None,
    max_files: int,
    max_bytes: int,
) -> list[Path]:
    """Walk directory and collect source files matching language filters."""
    files: list[Path] = []
    lang_filter = set(languages) if languages else None

    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if not path.is_file():
            continue
        if any(d in path.parts for d in IGNORE_DIRS):
            continue
        lang = EXT_TO_LANG.get(path.suffix.lower())
        if not lang:
            continue
        if lang_filter and lang not in lang_filter:
            continue
        try:
            if path.stat().st_size > max_bytes:
                continue
        except OSError:
            continue
        files.append(path)

    return files


# ── Hash-based change detection ───────────────────────────────────────────


def load_existing_hashes(store: MemoryStore) -> dict[str, tuple[int, str]]:
    """Load existing codebase memory hashes.

    Returns:
        Dict mapping file_path to (memory_id, content_hash).
    """
    hashes: dict[str, tuple[int, str]] = {}
    try:
        rows = store._conn.execute(
            "SELECT id, tags FROM memories WHERE agent_context = %s AND NOT is_stale",
            (CODEBASE_AGENT_CONTEXT,),
        ).fetchall()
        for row in rows:
            mem_id = row["id"]
            tags = row["tags"] if isinstance(row["tags"], list) else []
            file_path, content_hash = _extract_file_hash(tags)
            if file_path and content_hash:
                hashes[file_path] = (mem_id, content_hash)
    except Exception as exc:
        _log(f"hash load failed: {exc}")
    return hashes


def _extract_file_hash(tags: list) -> tuple[str, str]:
    """Extract file path and content hash from memory tags."""
    file_path, content_hash = "", ""
    for tag in tags:
        if isinstance(tag, str):
            if tag.startswith(FILE_TAG_PREFIX):
                file_path = tag[len(FILE_TAG_PREFIX) :]
            elif tag.startswith(HASH_TAG_PREFIX):
                content_hash = tag[len(HASH_TAG_PREFIX) :]
    return file_path, content_hash


def mark_stale(store: MemoryStore, memory_ids: list[int]) -> int:
    """Mark deleted file memories as stale."""
    if not memory_ids:
        return 0
    try:
        for mid in memory_ids:
            store._conn.execute(
                "UPDATE memories SET is_stale = TRUE, heat = 0 WHERE id = %s",
                (mid,),
            )
        store._conn.commit()
        return len(memory_ids)
    except Exception as exc:
        _log(f"mark stale failed: {exc}")
        return 0


# ── Entity persistence ────────────────────────────────────────────────────


def _get_or_create_entity(
    store: MemoryStore,
    name: str,
    entity_type: str,
    domain: str,
) -> int:
    """Find existing entity by name or create a new one. Returns entity ID."""
    existing = store.get_entity_by_name(name)
    if existing:
        return existing["id"]
    return store.insert_entity({"name": name, "type": entity_type, "domain": domain})


def _persist_symbol_entities(
    store: MemoryStore,
    analysis: FileAnalysis,
    file_eid: int,
    domain: str,
) -> tuple[int, int]:
    """Persist symbol definitions as entities with 'defines' relationships."""
    entities, relationships = 0, 0
    valid_kinds = {
        "function",
        "class",
        "interface",
        "type",
        "enum",
        "trait",
        "protocol",
        "constant",
        "struct",
    }
    for sym in analysis.definitions:
        kind = sym.kind if sym.kind in valid_kinds else "function"
        sym_eid = _get_or_create_entity(store, sym.name, kind, domain)
        entities += 1
        store.insert_relationship(
            {
                "source_entity_id": file_eid,
                "target_entity_id": sym_eid,
                "relationship_type": "defines",
                "weight": 1.0,
            }
        )
        relationships += 1
    return entities, relationships


def _persist_import_entities(
    store: MemoryStore,
    analysis: FileAnalysis,
    file_eid: int,
    domain: str,
) -> tuple[int, int]:
    """Persist import targets as dependency entities with 'imports' edges."""
    entities, relationships = 0, 0
    for imp in analysis.imports:
        dep_eid = _get_or_create_entity(store, imp.module, "dependency", domain)
        entities += 1
        store.insert_relationship(
            {
                "source_entity_id": file_eid,
                "target_entity_id": dep_eid,
                "relationship_type": "imports",
                "weight": 1.0,
            }
        )
        relationships += 1
    return entities, relationships


def persist_entities(
    store: MemoryStore,
    analysis: FileAnalysis,
    memory_id: int,
    domain: str,
) -> tuple[int, int]:
    """Persist file entity, symbols, and imports to knowledge graph.

    Returns:
        Tuple of (entities_created, relationships_created).
    """
    entities, relationships = 0, 0
    try:
        file_eid = _get_or_create_entity(store, analysis.path, "file", domain)
        entities += 1

        se, sr = _persist_symbol_entities(store, analysis, file_eid, domain)
        entities += se
        relationships += sr

        ie, ir = _persist_import_entities(store, analysis, file_eid, domain)
        entities += ie
        relationships += ir
    except Exception as exc:
        _log(f"entity persist failed for {analysis.path}: {exc}")

    return entities, relationships


# ── Graph edge persistence ────────────────────────────────────────────────


def persist_file_edge(
    store: MemoryStore,
    edges: list[tuple[str, str]],
    domain: str,
) -> int:
    """Store resolved file->file import edges as relationships."""
    count = 0
    for src_path, tgt_path in edges:
        try:
            src_eid = _get_or_create_entity(store, src_path, "file", domain)
            tgt_eid = _get_or_create_entity(store, tgt_path, "file", domain)
            store.insert_relationship(
                {
                    "source_entity_id": src_eid,
                    "target_entity_id": tgt_eid,
                    "relationship_type": "imports",
                    "weight": 1.0,
                }
            )
            count += 1
        except Exception:
            pass
    return count


def persist_inheritance_edge(
    store: MemoryStore,
    edges: list[tuple[str, str]],
    domain: str,
) -> int:
    """Store class->parent inheritance edges as relationships."""
    count = 0
    for child, parent in edges:
        try:
            child_eid = _get_or_create_entity(store, child, "class", domain)
            parent_eid = _get_or_create_entity(store, parent, "class", domain)
            store.insert_relationship(
                {
                    "source_entity_id": child_eid,
                    "target_entity_id": parent_eid,
                    "relationship_type": "extends",
                    "weight": 1.0,
                }
            )
            count += 1
        except Exception:
            pass
    return count


def persist_community_tags(
    store: MemoryStore,
    communities: dict[str, int],
) -> None:
    """Tag codebase memories with their community cluster ID."""
    for file_path, cluster_id in communities.items():
        try:
            store._conn.execute(
                "UPDATE memories SET tags = tags || %s::jsonb "
                "WHERE agent_context = 'codebase' "
                "AND tags @> %s::jsonb AND NOT is_stale",
                (
                    f'["cluster:{cluster_id}"]',
                    f'["file:{file_path}"]',
                ),
            )
        except Exception:
            pass
    if communities:
        try:
            store._conn.commit()
        except Exception:
            pass
