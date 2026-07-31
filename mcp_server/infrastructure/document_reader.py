"""Infrastructure: read a document off disk into the string its pure parser
expects. This is the ONLY layer that touches the filesystem / zip container
for document ingestion — the parsing (``core.docx_parser`` /
``core.confluence_parser``) is pure and receives strings from here.

A docx is an OOXML zip whose main part is ``word/document.xml`` (source:
ECMA-376 Part 2 "Open Packaging Conventions"); a Confluence export leg is a
storage-format XHTML file read as UTF-8 text. Both entry points raise
:class:`DocumentReadError` on a container/decoding failure — loud, so the
handler writes nothing (issue #192: malformed zip → hard error, no partial
silent write).
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# The OOXML main document part. source: ECMA-376 Part 1 §11.3.10 (Main
# Document Part), located via the package relationships; for every
# Word-authored .docx this is the fixed path below (Word never relocates it).
_DOCX_MAIN_PART = "word/document.xml"

# Cap mirrors ingest_docs_content_writers.MAX_DOC_BYTES (the AP per-file parse
# cap, automatised-pipeline/src/indexer/mod.rs:48 `MAX_PARSE_BYTES =
# 1_048_576`) applied to the UNCOMPRESSED main part / export text: a document
# body larger than 1 MB of XML is a pathological dump, not a realistic doc —
# reusing the same bound rather than inventing a second one (§8).
MAX_DOCUMENT_BYTES: int = 1_048_576


class DocumentReadError(Exception):
    """Raised when a document cannot be read from disk: missing file, not a
    valid zip, missing main part, oversized, or undecodable bytes. Loud by
    design so ingestion aborts before any write.

    TRY003 (issue #239): every raise site below names a distinct read/
    container failure (missing file, bad zip, missing part, oversized,
    bad decode) for a SPECIFIC document kind (docx vs. Confluence export)
    — each message is one-off, never reused, so a dedicated subclass per
    site would be premature abstraction (§3.3) that gains nothing over
    the shared ``DocumentReadError`` type this module already has. Two
    pairs share a near-identical SHAPE ("... exceeds N-byte cap" at
    L61/98-ish, "cannot .../not found" at L67/96-ish) but for two
    different document kinds at exactly 2 occurrences each — below the
    three-concrete-uses bar this module applies elsewhere (see
    entity_reconciliation.py's ``_require_ge`` for the 8-occurrence case
    that DID meet the bar). Marked with a bare `# noqa: TRY003` at each
    site rather than repeating this paragraph.
    """


def read_docx_xml(path: str | Path, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> str:
    """Unzip a .docx and return its ``word/document.xml`` as UTF-8 text.

    Precondition:  ``path`` points at a .docx (an OOXML zip).
    Postcondition: returns the decoded main-part XML string. The zip is only
                   probed for the single main part — no other member is read.
    Raises:        :class:`DocumentReadError` on a missing file, a corrupt /
                   non-zip container, an absent ``word/document.xml``, a
                   main part larger than ``max_bytes``, or undecodable bytes.
    """
    p = Path(path).expanduser()
    try:
        with zipfile.ZipFile(p) as archive:
            try:
                info = archive.getinfo(_DOCX_MAIN_PART)
            except KeyError as exc:
                raise DocumentReadError(  # noqa: TRY003
                    f"{p} is not a Word document: no {_DOCX_MAIN_PART}"
                ) from exc
            if info.file_size > max_bytes:
                raise DocumentReadError(  # noqa: TRY003
                    f"{p} main part is {info.file_size} bytes, exceeds "
                    f"{max_bytes}-byte cap"
                )
            raw = archive.read(_DOCX_MAIN_PART)
    except FileNotFoundError as exc:
        raise DocumentReadError(f"docx not found: {p}") from exc  # noqa: TRY003
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentReadError(f"cannot open docx {p}: {exc}") from exc  # noqa: TRY003

    try:
        # §12 note: the ``"utf-8"`` → ``"UTF-8"`` mutant is EQUIVALENT (codec
        # names are case-insensitive).
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentReadError(f"{p} main part is not valid UTF-8: {exc}") from exc  # noqa: TRY003


def read_confluence_export(
    path: str | Path, *, max_bytes: int = MAX_DOCUMENT_BYTES
) -> str:
    """Read a Confluence storage-format XHTML export file as UTF-8 text.

    Precondition:  ``path`` points at a single storage-format XHTML export
                   file (offline export leg — the live REST connector,
                   enterprise-backlog#28, fetches this same string over the
                   network instead and never touches this function).
    Postcondition: returns the file's UTF-8 text.
    Raises:        :class:`DocumentReadError` on a missing/oversized file or
                   undecodable bytes.
    """
    p = Path(path).expanduser()
    try:
        size = p.stat().st_size
    except OSError as exc:
        raise DocumentReadError(f"confluence export not found: {p}") from exc  # noqa: TRY003
    if size > max_bytes:
        raise DocumentReadError(f"{p} is {size} bytes, exceeds {max_bytes}-byte cap")  # noqa: TRY003
    # Read bytes then decode EXPLICITLY as UTF-8 (rather than read_text, whose
    # default encoding follows the platform locale) so the decoding is
    # locale-independent — the same explicit contract read_docx_xml uses.
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise DocumentReadError(f"cannot read confluence export {p}: {exc}") from exc  # noqa: TRY003
    try:
        # §12 note: ``"utf-8"`` → ``"UTF-8"`` is EQUIVALENT (case-insensitive).
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentReadError(f"{p} is not valid UTF-8: {exc}") from exc  # noqa: TRY003
