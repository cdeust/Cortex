"""The version of a Codex rollout a SessionEnd job delivered; stdlib only.

The intake persists an event inside its three-second hook budget and never
reads the rollout (ADR-1084): the detached drain hashes it. A receipt names
the last version the lifecycle received for one delivery identity
(ADR-1141), and a job is a replay only while the rollout still has those
bytes, so a rollout rewritten and then restored reaches the lifecycle again
(issue #716).

source: ADR-1145"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import tempfile

# source: ADR-1143 (transcript_fingerprint hashes in 1 MiB reads; the size
#   bounds memory, not the result)
CHUNK_BYTES = 1 << 20
# source: ADR-1145 (decision 2, the receipt field naming the version)
FIELD = "transcript_sha256"


def version(event, cwd):
    """SHA-256 of the rollout the SessionEnd closes, the ``sha256`` of
    ``transcript_fingerprint``; None when it names no readable file, a path
    ``open`` refuses included. A relative path is read from ``cwd``, the
    directory the lifecycle runs in, not the drain's (ADR-1146)."""
    path = event.get("transcript_path")
    if not isinstance(path, str) or not path:
        return None
    sha = hashlib.sha256()
    try:
        with open(os.path.join(cwd, path), "rb") as stream:
            for chunk in iter(functools.partial(stream.read, CHUNK_BYTES), b""):
                sha.update(chunk)
    except (OSError, ValueError):  # ValueError: a NUL byte in the path
        return None
    return sha.hexdigest()


def is_replay(receipt_path, current):
    """True when a receipt exists and names ``current``.

    Without a version now (no readable rollout), any receipt is a replay, as
    under ADR-1141. A receipt that names no version (written before
    ADR-1145, or unreadable) lets a readable rollout through once: the
    lifecycle then finds the same bytes and keeps its row (ADR-1143)."""
    try:
        recorded = json.loads(receipt_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except ValueError:
        recorded = None
    if current is None:
        return True
    return isinstance(recorded, dict) and recorded.get(FIELD) == current


def record(receipt_path, job, current):
    """Replace the receipt with ``job`` and the version it delivered; the
    caller syncs the directory."""
    fd, tmp = tempfile.mkstemp(dir=receipt_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({**job, FIELD: current}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, receipt_path)
    except BaseException:
        os.unlink(tmp)
        raise
