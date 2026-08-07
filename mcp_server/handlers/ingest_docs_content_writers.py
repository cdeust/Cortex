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

import hashlib
import logging
from pathlib import Path
from typing import Any
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)

# ai-architect-mcp-codebase's own per-file parse cap.
# source: ai-architect-mcp-codebase/src/indexer/mod.rs:48,
#   `pub const MAX_PARSE_BYTES: u64 = 1_048_576;` — "1 MB is sufficient
#   for any realistic source file" (mod.rs:46).
# Reused verbatim as the docs-pass skip threshold: a file AP itself
# would refuse to parse content-wise is not a realistic document either
# — no second, independently-invented bound. Measured headroom on this
# disk (2026-07-10): the largest .md in the Cortex repo is 154_622 bytes
# and in ai-architect-mcp-codebase's own repo well under 1 MB — real corpora
# sit far below this cap; it exists to bound the pathological case
# (a vendored dump or generated changelog checked in as .md).
MAX_DOC_BYTES: int = 1_048_576

_DOC_TAG_PREFIX = "ap-doc"

# Provenance tags (issue #381 — doc snapshots need a decidable revision
# stamp so a re-ingest can tell a stale snapshot from a current one).
#
# doc-sha256: the source file's content hash AT CAPTURE TIME — the
#   "revision" half of the {source_path, revision, captured_at} triple the
#   issue asks for. `captured_at` is not a separate tag: `created_at` is
#   already a first-class memories column, already surfaced by `recall`
#   (recall.py:297/361), and the DB default (now()) applies to every fresh
#   insert/supersession this pass performs — duplicating it as a tag would
#   be a second, driftable source of the same fact.
# doc-path: the source-relative path, structured (machine-parseable)
#   alongside the human-readable `[{rel_path}]` content header this pass
#   already writes.
#
# Hash length mirrors mcp_server/infrastructure/artifact_store.py's
# _ADDRESS_LEN (sha256 hex truncated to 16 chars / 64 bits — negligible
# birthday-collision risk for a per-repo document corpus, short enough to
# stay a readable tag); not a second, independently invented bound.
_DOC_HASH_TAG_LEN = 16
_DOC_HASH_TAG_PREFIX = "doc-sha256"
_DOC_PATH_TAG_PREFIX = "doc-path"


def doc_tag(domain: str, rel_path: str) -> str:
    """Canonical dedup tag anchoring a memory to one (domain, doc path)."""
    return f"{_DOC_TAG_PREFIX}:{domain}:{rel_path}"


def doc_content_hash(content: str) -> str:
    """Content-hash 'revision' stamp for a document snapshot (issue #381)."""
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

    Mirrors ``ingest_findings_writers.find_existing_memory``: stores
    without ``get_memories_by_tag`` (e.g. the SQLite fallback backend)
    degrade to "always create" rather than erroring — re-ingestion is
    then non-idempotent on that backend only, a pre-existing limitation
    of the tag-query API, not something this pass introduces.

    Postcondition: returns the full memory record (not just its id) so
    the caller can read its content-hash tag and decide whether the
    source has changed since capture (issue #381) — filtered to
    ``superseded_by_id is None`` so a supersession chain (this pass
    revises a memory in place by superseding it, never leaves two
    "current" rows) resolves to its open head, not an older link.
    """
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

    Precondition:  ``rel_path`` is relative to ``root`` — AP's ``File.path``
                    is repo-relative (verified against
                    ai-architect-mcp-codebase/src/indexer/walk.rs:237,
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
) -> tuple[int, bool, bool]:
    """Write, supersede, or reuse the memory representing this document.

    Postcondition: returns ``(memory_id, written, superseded)``.

    - No prior memory for this ``(domain, rel_path)``: inserts one, tagged
      with a content-hash "revision" stamp (issue #381) alongside the
      existing ``doc``/``src:ap``/dedup tags. Returns ``(new_id, True, False)``.
    - A prior memory exists and its stored content-hash tag still matches
      this read (source file unchanged since capture, OR a store that
      cannot tag-query and degrades to "no prior found" — see
      ``find_existing_doc_memory``): no-op, ``(existing_id, False, False)``
      — idempotence, D6's original acceptance criterion, now decided by
      content identity rather than by tag presence alone.
    - A prior memory exists and its content-hash tag differs (source file
      edited since capture, OR the prior memory predates this tag and so
      has none — see ``existing_content_hash``): the STALE snapshot is
      SUPERSEDED (Nader/Schafe/LeDoux 2000 reconsolidation — same
      ``store.supersede_atomic`` primitive ``remember`` uses for
      ``supersedes_id``, not a second, parallel versioning mechanism) —
      ``recall`` demotes a superseded row (pg_schema.py `current_memories`
      view / final ORDER BY) so a consumer is served the current snapshot,
      never the retracted one. Returns ``(new_id, True, True)``. On the
      bounded rebase exhausting (pathological concurrent-supersede
      contention — see ``supersede_atomic``'s own docstring), degrades to
      a no-write rather than raising: the next ingest run re-tries the
      comparison from a fresh read.

    Tags on every written row carry ``doc`` (D6's own wording), ``src:ap``
    (D5 provenance: this pass only ever runs over a graph AP produced),
    the per-document dedup tag, plus the two provenance tags above.
    """
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
