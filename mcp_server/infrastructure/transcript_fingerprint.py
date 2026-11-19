"""Fingerprint of a transcript file, and how a later version relates to it.

The SessionEnd lifecycle keys a session-log row on the transcript stem
(ADR-0497) and took any later row under the same stem for a replay. A
transcript that ended a second time with an earlier turn rewritten, or with
turns appended, lost its later version without a trace (issue #716,
acceptance item 3; audit P1 in
``docs/audits/transcript-capture-producers-2026-11-05.md``).

A row now records the size and SHA-256 of the transcript it was built from.
A later version is then one of three things: the same bytes (a replay), the
logged bytes followed by more (appended), or logged bytes changed
(rewritten). Only the first is skipped; the other two replace the row and
say so.

source: ADR-1143"""

from __future__ import annotations

import hashlib
from typing import Any

# How a later version of a logged transcript relates to it.
# source: ADR-1143 (decision 2)
REPLAY = "replay"
APPENDED = "appended"
REWRITTEN = "rewritten"

# Read size of one hashing step; it bounds memory, not the result.
# source: io.DEFAULT_BUFFER_SIZE is 8 KiB; 1 MiB keeps a 100 MB rollout
# to 100 reads without holding it in memory.
_CHUNK_BYTES = 1 << 20


def _digest(transcript_path: str, limit: int | None) -> tuple[int, str]:
    """Size read and SHA-256 of the file's first ``limit`` bytes (all if None)."""
    sha = hashlib.sha256()
    size = 0
    with open(transcript_path, "rb") as stream:
        while True:
            # Once ``limit`` bytes are read, ``want`` is 0 and read(0) is b"".
            want = _CHUNK_BYTES if limit is None else min(_CHUNK_BYTES, limit - size)
            chunk = stream.read(want)
            if not chunk:
                break
            sha.update(chunk)
            size += len(chunk)
    return size, sha.hexdigest()


def transcript_fingerprint(transcript_path: object) -> dict[str, Any] | None:
    """``{"bytes": n, "sha256": hex}`` of the transcript, or None.

    None when the event names no transcript or the file cannot be read: the
    row then carries ``"transcript": None`` and a later version under its
    stem cannot be compared with it (see ``relation``).
    """
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    try:
        size, sha = _digest(transcript_path, None)
    except OSError:
        return None
    return {"bytes": size, "sha256": sha}


def relation(
    transcript_path: object,
    logged: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> str | None:
    """How the transcript now on disk relates to the version a row logged.

    ``REPLAY`` for the same bytes, ``APPENDED`` when the logged bytes are a
    strict prefix of the current file, ``REWRITTEN`` otherwise. None when
    either version has no fingerprint (a row written before ADR-1143, or an
    unreadable file): nothing tells a replay from a new version, and the
    caller keeps the logged row as it did before.

    precondition: ``current`` is ``transcript_fingerprint(transcript_path)``
    taken under the same lifecycle lock.
    """
    if not logged or not current:
        return None
    if current["sha256"] == logged["sha256"]:
        return REPLAY
    # A file no longer than the logged one reads short or hashes differently.
    try:
        size, sha = _digest(str(transcript_path), logged["bytes"])
    except OSError:
        return None
    if size == logged["bytes"] and sha == logged["sha256"]:
        return APPENDED
    return REWRITTEN
