"""The one module that writes files Cortex persists.

Every text that reaches disk goes through :func:`redaction_gate.redact_text`
first: memory artifacts, the capture spool, wiki pages and their indexes,
project exports (``CLAUDE.md`` sections, ``docs/adr`` mirrors), JSON state
files, telemetry lines and log lines. ``tests_py/architecture`` fails any
other module of ``mcp_server/`` that calls a raw write primitive.

Writes are atomic (temporary file in the destination directory, fsync,
``os.replace``) except appends, which go through the rotation lock of
``log_rotation``.

source: ADR-1110"""

from __future__ import annotations

import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any, TextIO

from mcp_server.shared.private_paths import (
    PRIVATE_FILE_MODE,
    create_private_file,
    ensure_private_dir,
    is_private,
)
from mcp_server.shared.redaction_gate import redact_text, redact_value


_O_EXTRA = getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _atomic_write(
    path: Path, data: bytes, mode: int | None = None, exclusive: bool = False
) -> bytes:
    """Write ``data`` to ``path`` through a temporary file in the same directory.

    ``mode`` None: under Cortex's personal-data roots the file is ``0600``
    (ADR-1112); elsewhere a new file gets ``0o666`` minus the process umask
    (what ``open`` gives it) and a replaced file keeps its mode. ``exclusive``
    publishes with ``os.link``, which fails if ``path`` exists (``open("x")``)."""
    if mode is None and is_private(path):
        mode = PRIVATE_FILE_MODE  # source: ADR-1112
    ensure_private_dir(path.parent)
    try:
        keep_mode: int | None = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        keep_mode = None
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_EXTRA
    fd = os.open(tmp, flags, 0o666 if mode is None else mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        final_mode = mode if mode is not None else keep_mode
        if final_mode is not None:
            os.chmod(tmp, final_mode)
        if exclusive:
            os.link(tmp, path)
        else:
            os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return data


def write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int | None = None,
    exclusive: bool = False,
) -> bytes:
    """Atomically replace ``path`` with the redacted ``text``; return the bytes."""
    data = redact_text(text).encode(encoding)
    return _atomic_write(Path(path), data, mode, exclusive)


def write_bytes(
    path: str | Path, data: bytes, *, mode: int | None = None, exclusive: bool = False
) -> bytes:
    """Atomically replace ``path`` with ``data`` redacted as text.

    ``surrogateescape`` round-trips bytes that are not UTF-8 unchanged, so a
    restored file is byte-identical unless a secret was found in it."""
    text = data.decode("utf-8", "surrogateescape")
    redacted = redact_text(text).encode("utf-8", "surrogateescape")
    return _atomic_write(Path(path), redacted, mode, exclusive)


def write_json(
    path: str | Path, data: Any, *, mode: int | None = None, **dumps_kwargs: Any
) -> bytes:
    """Atomically write ``data`` as JSON; every string value is redacted."""
    return write_text(path, json.dumps(redact_value(data), **dumps_kwargs), mode=mode)


def append_text(path: str | Path, text: str, *, mode: int | None = None) -> None:
    """Append the redacted ``text`` under the log rotation lock."""
    from mcp_server.shared.log_rotation import open_rotating_log  # noqa: PLC0415 — log_rotation opens through this module; a top-level import would be circular

    redacted = redact_text(text)
    size = len(redacted.encode("utf-8"))
    with open_rotating_log(Path(path), size, mode) as stream:
        stream.write(redacted)


def open_text_log(path: str | Path) -> "RedactingStream":
    """Open ``path`` for appending; every write goes through the gate."""
    target = Path(path)
    if is_private(target):
        create_private_file(target)  # source: ADR-1112
    return RedactingStream(open(target, "a", encoding="utf-8"))  # noqa: SIM115 — the caller owns and closes the stream


class RedactingStream:
    """Text stream wrapper that redacts each write before it reaches disk.

    Line-oriented writers (``print``, ``logging.StreamHandler``) hand it whole
    lines, so a secret is never split across two writes."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        self._stream.write(redact_text(text))
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    @property
    def closed(self) -> bool:
        return self._stream.closed

    def fileno(self) -> int:
        raise OSError("a gated stream has no raw descriptor to hand out")

    def close(self) -> None:
        self._stream.close()
