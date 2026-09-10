"""Size rotation for JSONL appends and detached-worker log opens.

source: ADR-0655"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from mcp_server.shared.log_file_lock import log_file_lock

# source: ADR-0655

MAX_LOG_BYTES = 196_000 * 30


def methodology_log_path(filename: str) -> Path:
    """Use the same explicit local-data root as infrastructure/config.py."""
    override = os.environ.get("CORTEX_CLAUDE_DIR", "").strip()
    root = Path(override).expanduser() if override else Path.home() / ".claude"
    return root / "methodology" / filename


def _regular_file_size(path: Path) -> int:
    """A missing log starts empty; symlinks and special files are refused."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return 0
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"log is not a regular file: {path}")
    return info.st_size


def _rotate_if_needed(path: Path, incoming_bytes: int) -> None:
    size = _regular_file_size(path)
    if size and (size >= MAX_LOG_BYTES or size + incoming_bytes > MAX_LOG_BYTES):
        previous = path.with_name(path.name + ".1")
        _regular_file_size(previous)
        path.replace(previous)


@contextmanager
def open_rotating_log(path: Path, incoming_bytes: int = 0) -> Iterator[TextIO]:
    """Rotate/open under one lock; close the parent's descriptor on exit.

    The caller must keep its write or Popen inside this context. Any filesystem
    or locking error propagates to the writer's existing logged failure boundary.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with log_file_lock(path):
        _rotate_if_needed(path, incoming_bytes)
        with open(path, "a", encoding="utf-8", newline="\n") as stream:
            yield stream
