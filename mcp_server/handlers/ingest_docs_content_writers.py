"""Pure row builders + memory/relationship writers for the ingest_codebase
docs-content pass (INC5.3, design decision D6).

source: ADR-0407"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)

# source: ADR-0407
MAX_DOC_BYTES: int = 1_048_576

_DOC_TAG_PREFIX = "ap-doc"

# source: ADR-0407
_DOC_HASH_TAG_LEN = 16
_DOC_HASH_TAG_PREFIX = "doc-sha256"
_DOC_PATH_TAG_PREFIX = "doc-path"


def doc_tag(domain: str, rel_path: str) -> str:
    """Canonical dedup tag anchoring a memory to one (domain, doc path)."""
    return f"{_DOC_TAG_PREFIX}:{domain}:{rel_path}"


def doc_content_hash(content: str) -> str:
    """Content-hash 'revision' stamp for a document snapshot.

    source: ADR-0407"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:_DOC_HASH_TAG_LEN]


def doc_hash_tag(content_hash: str) -> str:
    """Tag encoding the source file's content hash at capture time."""
    return f"{_DOC_HASH_TAG_PREFIX}:{content_hash}"


def doc_path_tag(rel_path: str) -> str:
    """Tag encoding the source-relative path this memory was captured from."""
    return f"{_DOC_PATH_TAG_PREFIX}:{rel_path}"


def _memory_tags(mem: dict) -> list:
    raw = mem.get("tags", [])
    return raw if isinstance(raw, list) else []


def existing_content_hash(mem: dict) -> str | None:
    """Extract the ``doc-sha256`` provenance tag from a stored doc memory.

    Postcondition: returns the hash string, or None when the memory
    predates this tag (pre-#381 doc snapshot, or a store that dropped
    tags) — a caller comparing against None never equals a real hash, so
    an untagged legacy snapshot is always treated as changed and gets
    re-verified (re-written) exactly once on the next ingest.
    """
    prefix = f"{_DOC_HASH_TAG_PREFIX}:"
    for tag in _memory_tags(mem):
        if tag.startswith(prefix):
            return tag[len(prefix) :]
    return None


def find_existing_doc_memory(store: Any, domain: str, rel_path: str) -> dict | None:
    """Return the current chain-head memory already written for this
        document, or None.

    Postcondition: returns the full current memory record, filtered to
    ``superseded_by_id is None``.

    source: ADR-0407"""
    tag = doc_tag(domain, rel_path)
    try:
        mems = store.get_memories_by_tag(tag, limit=5)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("ingest_docs_content.find_existing_doc", exc)
        return None
    for mem in mems:
        if tag in _memory_tags(mem) and mem.get("superseded_by_id") is None:
            return mem
    return None


def read_doc_content(
    root: Path, rel_path: str, max_bytes: int = MAX_DOC_BYTES
) -> str | None:
    """Read one document's text off disk, or None if it should be skipped.

    Precondition: ``rel_path`` is relative to ``root``.
    Postcondition: returns UTF-8 text or None for a missing, oversized, or undecodable
    file. Logs the reason for every None result; never raises.

    source: ADR-0407"""
    abs_path = root / rel_path
    try:
        size = abs_path.stat().st_size
    except OSError:
        logger.debug("docs pass: %s not found on disk, skipping", abs_path)
        return None
    if size > max_bytes:
        logger.info(
            "docs pass: %s (%d bytes) exceeds %d-byte cap, skipping content",
            rel_path,
            size,
            max_bytes,
        )
        return None
    try:
        return abs_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        logger.debug("docs pass: %s unreadable (%s), skipping", abs_path, exc)
        return None


def write_doc_memory(
    store: Any,
    domain: str,
    directory_context: str,
    rel_path: str,
    content: str,
) -> tuple[int, bool, bool]:
    """Write, supersede, or reuse the memory representing this document.

        Postcondition: returns ``(memory_id, written, superseded)``.

    source: ADR-0407"""
    tag = doc_tag(domain, rel_path)
    content_hash = doc_content_hash(content)
    record = {
        "content": f"[{rel_path}]\n\n{content}",
        "tags": [
            "doc",
            "src:ap",
            tag,
            doc_hash_tag(content_hash),
            doc_path_tag(rel_path),
        ],
        "source": "ingest_codebase:docs",
        "domain": domain,
        "directory_context": directory_context,
        "importance": 0.5,
        "heat": 0.6,
        "confidence": 0.9,
        "is_protected": False,
        # M-D2 (7.4): bulk docs-content ingestion from an AP graph.
        "write_class": "mechanical",
    }

    existing = find_existing_doc_memory(store, domain, rel_path)
    if existing is None:
        return store.insert_memory(record), True, False

    if existing_content_hash(existing) == content_hash:
        return existing["id"], False, False

    new_id, _head_id = store.supersede_atomic(record, existing["id"])
    if new_id is None:
        return existing["id"], False, False
    return new_id, True, True


_REFERENCES_RELATIONSHIP_TYPE = "references"


def write_doc_reference_edge(store: Any, src_path: str, dst_path: str) -> bool:
    """Project one AP ``References_File_File`` edge into a KG relationship.

    Reuses the file entities the main ``ingest_codebase`` entity phase
    already inserted (every ``File`` node becomes an entity, docs and
    binaries alike) — this function inserts no entity, only the edge.

    Postcondition: returns True iff the edge was written. Both endpoint
    entities must already exist (``store.get_entity_by_name``); a missing
    endpoint means that file wasn't ingested this run (e.g. ``top_symbols``
    capped the entity phase before reaching it) and the edge is silently
    dropped — the same dangling-endpoint policy the containment/call
    edges already follow. Idempotent via ``insert_relationship``'s
    ``ON CONFLICT (source, target, type) DO UPDATE`` (pg_store_relationships.py).
    """
    src_entity = store.get_entity_by_name(src_path)
    dst_entity = store.get_entity_by_name(dst_path)
    if src_entity is None or dst_entity is None:
        return False
    store.insert_relationship(
        {
            "source_entity_id": src_entity["id"],
            "target_entity_id": dst_entity["id"],
            "relationship_type": _REFERENCES_RELATIONSHIP_TYPE,
            "weight": 1.0,
            "confidence": 0.9,
        }
    )
    return True
