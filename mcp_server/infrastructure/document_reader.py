"""Infrastructure: read a document off disk into the string its pure parser
expects. This is the ONLY layer that touches the filesystem / zip container
for document ingestion — the parsing (``core.docx_parser`` /
``core.confluence_parser``) is pure and receives strings from here.

source: ADR-0516"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# source: ADR-0516
_DOCX_MAIN_PART = "word/document.xml"

# source: ADR-0516
MAX_DOCUMENT_BYTES: int = 1_048_576


class DocumentReadError(Exception):
    """Signal a missing, invalid, oversized, or undecodable input document.

    source: ADR-0516"""


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
                raise DocumentReadError(
                    f"{p} is not a Word document: no {_DOCX_MAIN_PART}"
                ) from exc
            if info.file_size > max_bytes:
                raise DocumentReadError(
                    f"{p} main part is {info.file_size} bytes, exceeds "
                    f"{max_bytes}-byte cap"
                )
            raw = archive.read(_DOCX_MAIN_PART)
    except FileNotFoundError as exc:
        raise DocumentReadError(f"docx not found: {p}") from exc
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentReadError(f"cannot open docx {p}: {exc}") from exc

    try:
        # source: ADR-0516
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentReadError(f"{p} main part is not valid UTF-8: {exc}") from exc


def read_confluence_export(
    path: str | Path, *, max_bytes: int = MAX_DOCUMENT_BYTES
) -> str:
    """Read a Confluence storage-format XHTML export file as UTF-8 text.

    Precondition:  ``path`` points at a single storage-format XHTML export
                       file (offline export leg — the live REST connector,
                       enterprise-backlog#28, fetches this same string over the
                       network instead and never touches this function). Postcondition:
                       returns the file's UTF-8 text. Raises:
                       :class:`DocumentReadError` on a missing/oversized file or
                       undecodable bytes.

    source: ADR-0516"""
    p = Path(path).expanduser()
    try:
        size = p.stat().st_size
    except OSError as exc:
        raise DocumentReadError(f"confluence export not found: {p}") from exc
    if size > max_bytes:
        raise DocumentReadError(f"{p} is {size} bytes, exceeds {max_bytes}-byte cap")
    # source: ADR-0516
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise DocumentReadError(f"cannot read confluence export {p}: {exc}") from exc
    try:
        # source: ADR-0516
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentReadError(f"{p} is not valid UTF-8: {exc}") from exc
