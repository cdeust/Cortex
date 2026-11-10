"""Infrastructure: read a docx's relationships part and digest its media parts.

The pure side (``core.docx_relationships``) maps an image's relationship id to
the package part holding its bytes; this module is the zip I/O on both ends:
it returns the relationships part's text, then streams each named part
through SHA-256 so the bytes are identified without being held in memory.

source: issue #732 (slice 2); ECMA-376 Part 2 §9.3 (relationships part)
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Iterable
from pathlib import Path

from mcp_server.infrastructure.document_reader import (
    MAX_DOCUMENT_BYTES,
    DocumentReadError,
)

# source: ECMA-376 Part 2 §9.3.3 — the relationships of /word/document.xml
# live in /word/_rels/document.xml.rels.
_DOCX_RELS_PART = "word/_rels/document.xml.rels"
# source: CPython Lib/shutil.py COPY_BUFSIZE — the 64 KiB chunk
# shutil.copyfileobj reads on non-Windows platforms.
_CHUNK_BYTES = 65_536


def _open(path: str | Path) -> zipfile.ZipFile:
    """Open the docx container, mapping every failure to DocumentReadError."""
    p = Path(path).expanduser()
    try:
        return zipfile.ZipFile(p)
    except FileNotFoundError as exc:
        raise DocumentReadError(f"docx not found: {p}") from exc
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentReadError(f"cannot open docx {p}: {exc}") from exc


def read_docx_relationships_xml(
    path: str | Path, *, max_bytes: int = MAX_DOCUMENT_BYTES
) -> str:
    """Return the main part's relationships XML, or ``""`` when it has none.

    Postcondition: the decoded ``word/_rels/document.xml.rels`` text; ``""``
                   when the package holds no such part (a document whose
                   main part references no other part).
    Raises:        :class:`DocumentReadError` on a missing or corrupt
                   container, a part larger than ``max_bytes`` (the cap the
                   main part has, ADR-0516), a part whose bytes fail to
                   decompress or whose CRC does not match, or undecodable
                   bytes.

    source: issue #732; ADR-0516 (cap and UTF-8 rule)
    """
    with _open(path) as archive:
        try:
            info = archive.getinfo(_DOCX_RELS_PART)
        except KeyError:
            return ""
        if info.file_size > max_bytes:
            raise DocumentReadError(
                f"{path} relationships part is {info.file_size} bytes, "
                f"exceeds {max_bytes}-byte cap"
            )
        try:
            raw = archive.read(info)
        except (zipfile.BadZipFile, OSError, EOFError) as exc:
            raise DocumentReadError(
                f"cannot read {info.filename} in {path}: {exc}"
            ) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentReadError(
            f"{path} relationships part is not valid UTF-8: {exc}"
        ) from exc


def digest_docx_parts(
    path: str | Path, parts: Iterable[str]
) -> dict[str, tuple[str, int]]:
    """``{part: ("sha256:<hex>", size)}`` for each named part the package holds.

    Postcondition: a part absent from the container is absent from the
                   result, so the caller reports that image as unresolved.
                   Each part is read once, in chunks: memory stays bounded
                   whatever the image size.
    Raises:        :class:`DocumentReadError` on a missing or corrupt
                   container, or a member whose bytes fail to decompress
                   or whose CRC does not match.

    source: issue #732
    """
    found: dict[str, tuple[str, int]] = {}
    with _open(path) as archive:
        names = set(archive.namelist())
        for part in sorted(set(parts) & names):
            sha, size = hashlib.sha256(), 0
            try:
                with archive.open(part) as member:
                    while chunk := member.read(_CHUNK_BYTES):
                        sha.update(chunk)
                        size += len(chunk)
            except (zipfile.BadZipFile, OSError, EOFError) as exc:
                raise DocumentReadError(f"cannot read {part} in {path}: {exc}") from exc
            found[part] = (f"sha256:{sha.hexdigest()}", size)
    return found
