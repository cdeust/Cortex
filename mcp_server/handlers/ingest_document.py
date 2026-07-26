"""Handler: ingest_document — pull a .docx or Confluence export into Cortex.

Composition root (issue #192). Wires the pure parsers (``core.docx_parser`` /
``core.confluence_parser`` → ``core.document_normalizer``) to the filesystem
reader (``infrastructure.document_reader``) and the existing wiki/memory
write path (``wiki_write.write_governed_page`` + ``ingest_document_writers``).

The shared parsing/normalization seam this handler drives —
``parse_confluence_storage`` → ``normalize_document`` → the write path — is
exactly what the live-Confluence REST connector (enterprise-backlog#28, OUT
of scope here) consumes: that leg swaps only the byte source (REST fetch for
``read_confluence_export``) and the provenance (page URL + version for the
content hash), reusing every line of parsing, normalization and writing
below.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from mcp_server.core.document_model import (
    DocumentParseError,
    DocumentProvenance,
    ParsedDocument,
)
from mcp_server.core.confluence_parser import parse_confluence_storage
from mcp_server.core.docx_parser import parse_docx_xml
from mcp_server.core.document_normalizer import NormalizedDocument, normalize_document
from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE
from mcp_server.handlers.ingest_document_writers import (
    already_ingested,
    content_version,
    write_document_memories,
)
from mcp_server.handlers.wiki_write import write_governed_page
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.document_reader import (
    DocumentReadError,
    read_confluence_export,
    read_docx_xml,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store

logger = logging.getLogger(__name__)

_DOCX_EXTS = {".docx"}
_CONFLUENCE_EXTS = {".xml", ".xhtml", ".html", ".htm"}

schema = {
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Ingest a document (.docx or a Confluence storage-format XHTML "
        "export) into Cortex's memory/wiki store. Unpacks the container "
        "(docx = OOXML zip; Confluence = XHTML file), extracts heading "
        "structure + paragraph text + tables into a wiki reference page "
        "under documents/<slug>.md, and writes one protected summary memory "
        "plus one memory per section — every page and memory stamped with "
        "provenance (source path + content version) so documents ride the "
        "same staleness/validation path as code references. Embedded images "
        "are skipped with an explicit notice (no OCR). Re-ingesting the same "
        "document version is idempotent (no duplicate writes). Malformed "
        "zip/XML fails loudly, writing nothing. Distinct from `ingest_prd` "
        "(markdown PRDs with decision/requirement extraction), "
        "`ingest_codebase` (code symbols), and `wiki_write` (manual single "
        "page). Returns {ingested, wiki_path, summary_memory_id, "
        "section_count, images_skipped, notices, idempotent_skip}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute path to a .docx file or a Confluence "
                    "storage-format XHTML export file."
                ),
                "examples": [
                    "/Users/alice/docs/spec.docx",
                    "/Users/alice/export/Onboarding.xml",
                ],
            },
            "format": {
                "type": "string",
                "description": (
                    "Document format. 'auto' infers from the file extension "
                    "(.docx → docx; .xml/.xhtml/.html → confluence)."
                ),
                "enum": ["auto", "docx", "confluence"],
                "default": "auto",
            },
            "title": {
                "type": "string",
                "description": (
                    "Override the document title (else derived from the first "
                    "heading, else the filename)."
                ),
            },
            "domain": {
                "type": "string",
                "description": "Cognitive domain to tag the ingested memories with.",
                "examples": ["myapp", "team-wiki"],
            },
        },
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = cast(
            MemoryStore, get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
        )
    return _store


def _resolve_format(path: Path, explicit: str) -> str:
    """Map the requested format to a concrete adapter kind, or '' if unknown.

    Postcondition: returns 'docx' or 'confluence-export' (the two offline
    adapters), or '' when 'auto' cannot infer a supported format from the
    extension — the handler turns '' into a loud, no-write error."""
    if explicit == "docx":
        return "docx"
    if explicit == "confluence":
        return "confluence-export"
    ext = path.suffix.lower()
    if ext in _DOCX_EXTS:
        return "docx"
    if ext in _CONFLUENCE_EXTS:
        return "confluence-export"
    return ""


def _read_and_parse(path: Path, kind: str, title: str) -> tuple[ParsedDocument, str]:
    """Read the document off disk (infra) and parse it (core).

    Postcondition: returns ``(parsed, raw_text)`` where ``raw_text`` is the
    exact string parsed (its hash is the content version). Raises
    :class:`DocumentReadError` (container/decoding failure) or
    :class:`DocumentParseError` (malformed markup) — both loud, both before
    any write."""
    if kind == "docx":
        raw = read_docx_xml(path)
        return parse_docx_xml(raw, title=title), raw
    raw = read_confluence_export(path)
    return parse_confluence_storage(raw, title=title), raw


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ingest a .docx or Confluence export into Cortex (issue #192).

    Postcondition: on success writes exactly one wiki page + one summary
    memory + one memory per section, all provenance-stamped, and returns
    ``ingested: True``. A repeat ingest of the same (source, version) writes
    nothing and returns ``idempotent_skip: True``. A read/parse failure
    returns ``ingested: False`` with a reason and writes NOTHING."""
    args = args or {}
    raw_path = str(args.get("path") or "").strip()
    if not raw_path:
        return {"ingested": False, "reason": "path is required"}

    path = Path(raw_path).expanduser()
    # §12 note: the ``"auto"`` literal here is a documentation default — mutating
    # it is EQUIVALENT, since _resolve_format treats every value other than
    # "docx"/"confluence" identically (extension-based inference).
    kind = _resolve_format(path, str(args.get("format") or "auto"))
    if not kind:
        return {
            "ingested": False,
            "reason": f"unsupported document format for {path.name} "
            "(expected .docx or a Confluence .xml/.xhtml/.html export)",
        }

    title = str(args.get("title") or "").strip()
    try:
        parsed, raw = _read_and_parse(path, kind, title)
    except DocumentReadError as exc:
        return {"ingested": False, "reason": "document_read_failed", "error": str(exc)}
    except DocumentParseError as exc:
        return {"ingested": False, "reason": "document_parse_failed", "error": str(exc)}

    prov = DocumentProvenance(
        source=str(path), version=content_version(raw), source_kind=kind
    )
    domain = (str(args.get("domain") or "").strip()) or "documents"
    return await _persist(path, kind, parsed, prov, domain)


def _skip_response(
    existing: int,
    parsed: ParsedDocument,
    prov: DocumentProvenance,
    normalized: NormalizedDocument,
) -> dict[str, Any]:
    """The response for a re-ingest of an already-stored (source, version)."""
    return {
        "ingested": True,
        "idempotent_skip": True,
        "reason": "already ingested at this version",
        "summary_memory_id": existing,
        "title": parsed.title,
        "version": prov.version,
        "images_skipped": normalized.image_count,
        "notices": normalized.notices,
    }


async def _persist(
    path: Path,
    kind: str,
    parsed: ParsedDocument,
    prov: DocumentProvenance,
    domain: str,
) -> dict[str, Any]:
    """Write the wiki page + memories for a freshly-parsed document, or skip
    idempotently if this (source, version) was already ingested.

    Postcondition: on a first ingest, exactly one wiki page + one summary
    memory + one memory per section are written (all provenance-stamped) and a
    full response is returned; a repeat returns an idempotent-skip response and
    writes nothing. A wiki-write failure sets ``wiki_path`` to None and is
    logged (never silent) but does not abort the memory writes."""
    normalized = normalize_document(parsed, prov)
    store = _get_store()
    existing = already_ingested(store, prov)
    if existing is not None:
        return _skip_response(existing, parsed, prov, normalized)

    page = await write_governed_page(
        WIKI_ROOT,
        normalized.wiki_rel_path,
        normalized.wiki_markdown,
        mode="replace",
        tags=["document", "ingest", kind],
    )
    wiki_path = (
        None
        if isinstance(page, dict) and page.get("error")
        else normalized.wiki_rel_path
    )
    if wiki_path is None:
        logger.warning("ingest_document wiki write failed: %s", page)

    directory = str(path.resolve().parent)
    written = write_document_memories(store, normalized, prov, domain, directory)
    return {
        "ingested": True,
        "idempotent_skip": False,
        "title": parsed.title,
        "source": prov.source,
        "source_kind": kind,
        "version": prov.version,
        "wiki_path": wiki_path,
        "summary_memory_id": written["summary_memory_id"],
        "section_count": len(written["section_memory_ids"]),
        "images_skipped": normalized.image_count,
        "notices": normalized.notices,
    }


__all__ = ["handler", "schema"]
