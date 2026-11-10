"""Infrastructure: read a docx's relationships part and digest its media parts.

The pure side (``core.docx_relationships``) maps an image's relationship id to
the package part holding its bytes; this module is the zip I/O on both ends:
it returns the relationships part's text, then streams each named part
through SHA-256 so the bytes are identified without being held in memory.

source: issue #732 (slice 2); ECMA-376 Part 2 §9.3 (relationships part)
"""

from __future__ import annotations

import hashlib
import lzma
import zipfile
import zlib
from collections.abc import Callable, Iterable
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
# source: CPython Lib/zipfile — what reading a member's bytes can raise:
# BadZipFile (bad CRC, truncated header), EOFError (truncated data),
# zlib.error / lzma.LZMAError (corrupt deflate / LZMA stream; bzip2 raises
# OSError), NotImplementedError (unsupported compression method),
# RuntimeError (encrypted member, no password), OSError (I/O).
_MEMBER_READ_ERRORS = (
    zipfile.BadZipFile,
    EOFError,
    zlib.error,
    lzma.LZMAError,
    NotImplementedError,
    RuntimeError,
    OSError,
)


def _open(path: str | Path) -> zipfile.ZipFile:
    """Open the docx container, mapping every failure to DocumentReadError."""
    p = Path(path).expanduser()
    try:
        return zipfile.ZipFile(p)
    except FileNotFoundError as exc:
        raise DocumentReadError(f"docx not found: {p}") from exc
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentReadError(f"cannot open docx {p}: {exc}") from exc


def _stream_member(
    archive: zipfile.ZipFile, name: str, path: str | Path, sink: Callable[[bytes], None]
) -> None:
    """Feed member ``name``'s bytes to ``sink`` in chunks; any failure to read
    or decompress them becomes one :class:`DocumentReadError`.

    source: issue #732 (Codex review of PR #961: CRC, then deflate errors)"""
    try:
        with archive.open(name) as member:
            while chunk := member.read(_CHUNK_BYTES):
                sink(chunk)
    except _MEMBER_READ_ERRORS as exc:
        raise DocumentReadError(f"cannot read {name} in {path}: {exc}") from exc


def _digest_member(
    archive: zipfile.ZipFile, name: str, path: str | Path
) -> tuple[str, int]:
    """``("sha256:<hex>", size)`` of member ``name``, streamed.

    source: issue #732"""
    sha, sizes = hashlib.sha256(), [0]

    def _sink(chunk: bytes) -> None:
        sha.update(chunk)
        sizes[0] += len(chunk)

    _stream_member(archive, name, path, _sink)
    return f"sha256:{sha.hexdigest()}", sizes[0]


def read_docx_relationships_xml(
    path: str | Path, *, max_bytes: int = MAX_DOCUMENT_BYTES
) -> str:
    """Return the main part's relationships XML, or ``""`` when it has none.

    Postcondition: the decoded ``word/_rels/document.xml.rels`` text; ``""``
                   when the package holds no such part (a document whose
                   main part references no other part).
    Raises:        :class:`DocumentReadError` on a missing or corrupt
                   container, a part larger than ``max_bytes`` (the cap the
                   main part has, ADR-0516), a part whose bytes cannot be
                   read or decompressed (``_MEMBER_READ_ERRORS``), or
                   undecodable bytes.

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
        raw = bytearray()
        _stream_member(archive, info.filename, path, raw.extend)
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
                   container, or a member whose bytes cannot be read or
                   decompressed (``_MEMBER_READ_ERRORS``).

    source: issue #732
    """
    found: dict[str, tuple[str, int]] = {}
    with _open(path) as archive:
        names = set(archive.namelist())
        for part in sorted(set(parts) & names):
            found[part] = _digest_member(archive, part, path)
    return found
