"""Pure row builders + memory/relationship writers for the ingest_codebase
docs-content pass (INC5.3, design decision D6).

D6 (inc5-design-decouverte-documentation.md): document CONTENT indexing
happens on Cortex's side, never AP's — AP stores every file (docs
included) as a ``File`` node but never its content (persist.rs:60-81)
and excludes ``File`` from its own BM25 index by construction
(bm25.rs:43-46). This module reads the Markdown-family file bytes off
disk — the ``ingest_codebase`` handler already knows the project root
(D6's "no meta.json needed" point, since the handler was GIVEN
``project_path``) — and writes one memory per document, tagged for
idempotent re-ingestion.

Relations reuse the file entities already inserted, for EVERY file
(docs included), by ``ingest_codebase_writers.file_entity_row`` in the
handler's main entity phase — this module only adds the
``References_File_File`` edges AP's light-link post-pass already
extracted, via ``MemoryStore.insert_relationship`` (ON CONFLICT-
idempotent, see ``pg_store_relationships.py``). Binaries (.pdf, .docx)
get no special handling here: they were already registered as
content-less file entities by the generic files phase, matching D6's
"pas de parseur — dire je ne sais pas plutôt qu'extraire mal".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)

# automatised-pipeline's own per-file parse cap.
# source: automatised-pipeline/src/indexer/mod.rs:48,
#   `pub const MAX_PARSE_BYTES: u64 = 1_048_576;` — "1 MB is sufficient
#   for any realistic source file" (mod.rs:46).
# Reused verbatim as the docs-pass skip threshold: a file AP itself
# would refuse to parse content-wise is not a realistic document either
# — no second, independently-invented bound. Measured headroom on this
# disk (2026-07-10): the largest .md in the Cortex repo is 154_622 bytes
# and in automatised-pipeline's own repo well under 1 MB — real corpora
# sit far below this cap; it exists to bound the pathological case
# (a vendored dump or generated changelog checked in as .md).
MAX_DOC_BYTES: int = 1_048_576

_DOC_TAG_PREFIX = "ap-doc"


def doc_tag(domain: str, rel_path: str) -> str:
    """Canonical dedup tag anchoring a memory to one (domain, doc path)."""
    return f"{_DOC_TAG_PREFIX}:{domain}:{rel_path}"


def _memory_tags(mem: dict) -> list:
    raw = mem.get("tags", [])
    return raw if isinstance(raw, list) else []


def find_existing_doc_memory(store: Any, domain: str, rel_path: str) -> int | None:
    """Return the memory id already written for this document, or None.

    Mirrors ``ingest_findings_writers.find_existing_memory``: stores
    without ``get_memories_by_tag`` (e.g. the SQLite fallback backend)
    degrade to "always create" rather than erroring — re-ingestion is
    then non-idempotent on that backend only, a pre-existing limitation
    of the tag-query API, not something this pass introduces.
    """
    tag = doc_tag(domain, rel_path)
    try:
        mems = store.get_memories_by_tag(tag, limit=5)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("ingest_docs_content.find_existing_doc", exc)
        return None
    for mem in mems:
        if tag in _memory_tags(mem):
            return mem.get("id")
    return None


def read_doc_content(
    root: Path, rel_path: str, max_bytes: int = MAX_DOC_BYTES
) -> str | None:
    """Read one document's text off disk, or None if it should be skipped.

    Precondition:  ``rel_path`` is relative to ``root`` — AP's ``File.path``
                    is repo-relative (verified against
                    automatised-pipeline/src/indexer/walk.rs:237,
                    ``file_path.strip_prefix(root)``).
    Postcondition: returns decoded UTF-8 text, or None (missing file,
                    file larger than ``max_bytes``, or undecodable bytes)
                    — never raises. Every None path is logged with its
                    reason so a skipped document is diagnosable, not
                    silent.
    """
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
) -> tuple[int, bool]:
    """Write (or reuse) the one memory representing this document's content.

    Postcondition: returns ``(memory_id, created)``. ``created`` is False
    when an earlier ingestion of the same ``(domain, rel_path)`` already
    wrote this memory — re-ingesting an unchanged graph inserts no
    duplicate row (idempotence, D6 acceptance criterion). Tags carry
    ``doc`` (D6's own wording) and ``src:ap`` (D5 provenance: this pass
    only ever runs over a graph AP produced) plus the per-document dedup
    tag.
    """
    existing = find_existing_doc_memory(store, domain, rel_path)
    if existing is not None:
        return existing, False

    tag = doc_tag(domain, rel_path)
    record = {
        "content": f"[{rel_path}]\n\n{content}",
        "tags": ["doc", "src:ap", tag],
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
    return store.insert_memory(record), True


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
