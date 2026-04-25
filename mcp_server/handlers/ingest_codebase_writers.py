"""Cortex-side writers for ingest_codebase.

Project the upstream graph projection (symbols, files, edges) into
Cortex's MemoryStore: memories, KG entities, and KG relationships.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def _short_symbol_summary(sym: dict[str, Any]) -> str:
    """Compact one-line summary for a ranked symbol."""
    qn = sym.get("qualified_name") or sym.get("name") or "<anon>"
    kind = sym.get("kind") or sym.get("label") or "symbol"
    community = sym.get("community")
    process = sym.get("process")
    parts = [f"{kind} {qn}"]
    if community is not None:
        parts.append(f"community={community}")
    if process:
        parts.append(f"process={process}")
    return " | ".join(parts)


def write_symbol_memories(
    store: MemoryStore,
    symbols: list[dict[str, Any]],
    project_path: str,
    domain: str,
) -> list[int]:
    """Persist symbols as standalone memories. Returns new memory ids."""
    ids: list[int] = []
    for sym in symbols:
        qn = sym.get("qualified_name") or sym.get("name")
        if not qn:
            continue
        summary = _short_symbol_summary(sym)
        content = f"Code symbol: {qn}\n\n{summary}"
        if sym.get("file"):
            content += f"\nFile: {sym['file']}"
        record = {
            "content": content,
            "tags": ["code-reference", "ingest", sym.get("kind", "symbol")],
            "source": "ingest_codebase",
            "domain": domain,
            "directory_context": project_path,
            "importance": float(sym.get("relevance_score", 0.5) or 0.5),
            "heat": 0.8,
            "is_protected": False,
        }
        try:
            ids.append(store.insert_memory(record))
        except (ValueError, KeyError, TypeError) as exc:
            logger.debug("symbol memory insert failed for %s: %s", qn, exc)
    return ids


def write_symbol_entities(
    store: MemoryStore,
    symbols: list[dict[str, Any]],
    domain: str,
) -> tuple[dict[str, int], list[str]]:
    """Persist symbols as KG entities. Returns (name_to_id, diagnostics).

    qualified_name is the dedupe key. When two distinct symbols share
    a qn (overloads, decorator-generated copies, indexer noise) we can
    only retain one entity, since call edges from the upstream graph
    are themselves keyed on qn — disambiguating downstream would
    require signatures the upstream does not emit. We surface
    collisions as diagnostics so the user can see the loss is honest.
    """
    name_to_id: dict[str, int] = {}
    collisions: dict[str, int] = {}
    for sym in symbols:
        qn = sym.get("qualified_name") or sym.get("name")
        if not qn:
            continue
        if qn in name_to_id:
            collisions[qn] = collisions.get(qn, 1) + 1
            continue
        try:
            eid = store.insert_entity(
                {
                    "name": qn,
                    "type": sym.get("kind", "symbol"),
                    "domain": domain,
                    "heat": 0.8,
                }
            )
            name_to_id[qn] = eid
        except (ValueError, KeyError, TypeError) as exc:
            logger.debug("symbol entity insert failed for %s: %s", qn, exc)
    diagnostics: list[str] = []
    if collisions:
        total = sum(collisions.values())
        sample = ", ".join(sorted(collisions.keys())[:3])
        diagnostics.append(
            f"qn-collision: {len(collisions)} qualified_names had {total} duplicate "
            f"symbols (kept first). sample: {sample}"
        )
    return name_to_id, diagnostics


def write_symbol_relationships(
    store: MemoryStore,
    edges: list[tuple[str, str]],
    name_to_id: dict[str, int],
) -> int:
    """Persist call edges between known entities.

    Only edges where BOTH endpoints are present in ``name_to_id`` are
    materialised — anything else would be a dangling reference.
    """
    written = 0
    for src_name, target_name in edges:
        src_id = name_to_id.get(src_name)
        dst_id = name_to_id.get(target_name)
        if src_id is None or dst_id is None or src_id == dst_id:
            continue
        try:
            store.insert_relationship(
                {
                    "source_entity_id": src_id,
                    "target_entity_id": dst_id,
                    "relationship_type": "calls",
                    "weight": 1.0,
                    "confidence": 0.9,
                }
            )
            written += 1
        except (ValueError, KeyError, TypeError) as exc:
            logger.debug(
                "edge insert failed (%s → %s): %s", src_name, target_name, exc
            )
    return written


def write_file_memories(
    store: MemoryStore,
    files: list[dict[str, Any]],
    project_path: str,
    domain: str,
) -> list[int]:
    """Persist files as standalone memories. Returns new memory ids."""
    ids: list[int] = []
    for f in files:
        path = f.get("path")
        if not path:
            continue
        ext = f.get("extension") or ""
        size = f.get("size_bytes") or 0
        record = {
            "content": f"Code file: {path}\n\nextension={ext} | size_bytes={size}",
            "tags": ["code-reference", "ingest", "file"],
            "source": "ingest_codebase",
            "domain": domain,
            "directory_context": project_path,
            "importance": 0.4,
            "heat": 0.6,
            "is_protected": False,
        }
        try:
            ids.append(store.insert_memory(record))
        except (ValueError, KeyError, TypeError) as exc:
            logger.debug("file memory insert failed for %s: %s", path, exc)
    return ids


def write_file_entities(
    store: MemoryStore,
    files: list[dict[str, Any]],
    domain: str,
) -> dict[str, int]:
    """Persist files as KG entities. Returns {file_path: entity_id}.

    Files dedupe by path; duplicate paths from upstream are silently
    coalesced (the upstream indexer guarantees per-path uniqueness).
    """
    name_to_id: dict[str, int] = {}
    for f in files:
        path = f.get("path")
        if not path or path in name_to_id:
            continue
        try:
            eid = store.insert_entity(
                {
                    "name": path,
                    "type": "file",
                    "domain": domain,
                    "heat": 0.6,
                }
            )
            name_to_id[path] = eid
        except (ValueError, KeyError, TypeError) as exc:
            logger.debug("file entity insert failed for %s: %s", path, exc)
    return name_to_id


def write_file_relationships(
    store: MemoryStore,
    edges: list[tuple[str, str]],
    file_to_id: dict[str, int],
    symbol_to_id: dict[str, int],
) -> int:
    """Persist (file)-[:contains]->(symbol) edges."""
    written = 0
    for file_path, symbol_qn in edges:
        src_id = file_to_id.get(file_path)
        dst_id = symbol_to_id.get(symbol_qn)
        if src_id is None or dst_id is None:
            continue
        try:
            store.insert_relationship(
                {
                    "source_entity_id": src_id,
                    "target_entity_id": dst_id,
                    "relationship_type": "contains",
                    "weight": 1.0,
                    "confidence": 0.95,
                }
            )
            written += 1
        except (ValueError, KeyError, TypeError) as exc:
            logger.debug(
                "file edge insert failed (%s → %s): %s",
                file_path,
                symbol_qn,
                exc,
            )
    return written
