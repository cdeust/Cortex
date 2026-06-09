"""Helpers for codebase_analyze — file walking, hashing, entity persistence."""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

from mcp_server.core.codebase_parser import EXT_TO_LANG, FileAnalysis
from mcp_server.handlers.seed_project_constants import IGNORE_DIRS
from mcp_server.handlers.source_walk import walk_pruned
from mcp_server.infrastructure.memory_store import MemoryStore

CODEBASE_AGENT_CONTEXT = "codebase"
FILE_TAG_PREFIX = "file:"
HASH_TAG_PREFIX = "hash:"

# Bounded-candidate multiplier: we take at most ``max_files * CANDIDATE_MULTIPLIER``
# paths from the pruned walk before sorting. Source: ADR-0045 §R2 — bounded streaming
# for ingestion paths. The multiplier gives the sort a meaningful candidate set while
# keeping peak memory O(max_files) instead of O(tree_size).
CANDIDATE_MULTIPLIER = 10


def _log(msg: str) -> None:
    print(f"[codebase-analyze] {msg}", file=sys.stderr)


# ── File walking ──────────────────────────────────────────────────────────


def collect_source_files(
    root: Path,
    languages: list[str] | None,
    max_files: int,
    max_bytes: int,
) -> list[Path]:
    """Walk directory and collect source files matching language filters.

    Preconditions:
        - ``root`` is an existing directory.
        - ``max_bytes > 0``.
        - ``max_files`` may be any integer; ``<= 0`` means "no limit" and
          processes every matching file in the tree.

    Postconditions:
        - When ``max_files > 0``: returns at most ``max_files`` paths,
          and peak memory is O(max_files * CANDIDATE_MULTIPLIER) paths
          (ADR-0045 §R2). On a 10M-file monorepo with ``max_files=5000``
          we hold at most 50K Path objects during the sort.
        - When ``max_files <= 0``: returns every matching path. Peak
          memory is O(filtered_files) — we never materialise the whole
          tree, only the post-filter survivors.
        - Each returned path is a regular file whose extension maps to a
          known language (and satisfies ``languages`` if supplied), and
          whose size is ``<= max_bytes``.
    """
    lang_filter = set(languages) if languages else None
    unbounded = max_files <= 0

    if unbounded:
        return _collect_unbounded(root, lang_filter, max_bytes)
    return _collect_bounded(root, lang_filter, max_files, max_bytes)


def _file_matches(
    path: Path,
    lang_filter: set[str] | None,
    max_bytes: int,
) -> bool:
    """Return True iff ``path`` is a source file we should keep."""
    if not path.is_file():
        return False
    if any(d in path.parts for d in IGNORE_DIRS):
        return False
    lang = EXT_TO_LANG.get(path.suffix.lower())
    if not lang:
        return False
    if lang_filter and lang not in lang_filter:
        return False
    try:
        if path.stat().st_size > max_bytes:
            return False
    except OSError:
        return False
    return True


def _collect_unbounded(
    root: Path,
    lang_filter: set[str] | None,
    max_bytes: int,
) -> list[Path]:
    """Walk the pruned tree, filter, then sort. Memory O(filtered_count).

    Uses ``walk_pruned`` (not ``rglob``) so vendored subtrees in IGNORE_DIRS
    are never descended into — a repo carrying a 154M ``deps/`` no longer
    stalls the walk for minutes before the extension filter rejects it.
    """
    survivors = [
        p for p in walk_pruned(root) if _file_matches(p, lang_filter, max_bytes)
    ]
    survivors.sort()
    return survivors


def _collect_bounded(
    root: Path,
    lang_filter: set[str] | None,
    max_files: int,
    max_bytes: int,
) -> list[Path]:
    """Bounded-candidate walk: take ``max_files * CANDIDATE_MULTIPLIER`` paths
    then sort for deterministic ordering. See ADR-0045 §R2.
    """
    candidate_cap = max(max_files * CANDIDATE_MULTIPLIER, max_files)
    candidates = sorted(itertools.islice(walk_pruned(root), candidate_cap))

    files: list[Path] = []
    for path in candidates:
        if len(files) >= max_files:
            break
        if _file_matches(path, lang_filter, max_bytes):
            files.append(path)
    return files


# ── Hash-based change detection ───────────────────────────────────────────


def _parse_tags(raw: object) -> list:
    """Parse tags from a list (PG) or JSON string (SQLite)."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        import json

        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return []
    return []


def load_existing_hashes(store: MemoryStore) -> dict[str, tuple[int, str]]:
    """Load existing codebase memory hashes: {path: (id, hash)}.

    Phase 5: batch pool (part of a codebase-analyze job).
    """
    hashes: dict[str, tuple[int, str]] = {}
    try:
        with store.acquire_batch() as conn:
            rows = conn.execute(
                "SELECT id, tags FROM memories "
                "WHERE agent_context = %s AND NOT is_stale",
                (CODEBASE_AGENT_CONTEXT,),
            ).fetchall()
        for row in rows:
            mem_id = row["id"]
            tags = _parse_tags(row["tags"])
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
    """Mark deleted file memories as stale.

    The legacy ``heat = 0`` clause was redundant with ``is_stale = TRUE``
    — every scan filters ``NOT is_stale`` before the heat signal is
    consulted, so the heat value on stale rows is never read. A3 drops
    the redundant zeroing; the heat_base column keeps its last value.
    Source: phase-3-a3-migration-design.md §3.6.
    """
    if not memory_ids:
        return 0
    try:
        with store.acquire_batch() as conn:
            for mid in memory_ids:
                conn.execute(
                    "UPDATE memories SET is_stale = TRUE WHERE id = %s",
                    (mid,),
                )
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
    """Persist file entity, symbols, and imports. Returns (entities, rels)."""
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
    """Tag codebase memories with their community cluster ID.

    Phase 5: batch pool (part of a codebase-analyze job).
    """
    import json

    if not communities:
        return
    with store.acquire_batch() as conn:
        for file_path, cluster_id in communities.items():
            try:
                rows = conn.execute(
                    "SELECT id, tags FROM memories "
                    "WHERE agent_context = 'codebase' AND NOT is_stale "
                    "AND content LIKE %s",
                    (f"%{file_path}%",),
                ).fetchall()
                for row in rows:
                    tags = _parse_tags(row["tags"])
                    tag = f"cluster:{cluster_id}"
                    if tag not in tags:
                        tags.append(tag)
                        conn.execute(
                            "UPDATE memories SET tags = %s WHERE id = %s",
                            (json.dumps(tags), row["id"]),
                        )
            except Exception:
                pass
