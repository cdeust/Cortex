"""Generic filesystem operations for JSON and text files.

source: ADR-0526"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def read_json(file_path: str | Path) -> Any | None:
    """Read and parse a JSON file. Returns None if missing/corrupt."""
    try:
        p = Path(file_path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        print(f"[methodology-agent] Failed to read {file_path}: {e}", file=sys.stderr)
    return None


def write_json(file_path: str | Path, data: Any) -> None:
    """Write an object as JSON, creating parent directories as needed.

    source: ADR-0526"""
    p = Path(file_path)
    ensure_dir(p.parent)
    tmp = p.with_suffix(f"{p.suffix}.tmp-{os.getpid()}")
    # source: ADR-1084 (acknowledge lifecycle effects only after persistence).
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, p)
    _sync_directory(p.parent)


def read_text_file(file_path: str | Path) -> str | None:
    """Read a text file. Returns None if missing."""
    try:
        p = Path(file_path)
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        print(f"[methodology-agent] Failed to read {file_path}: {e}", file=sys.stderr)
    return None


def ensure_dir(dir_path: str | Path) -> None:
    """Ensure a directory exists, creating it recursively if needed.

    source: ADR-0526"""
    # source: ADR-1084 (new directory links must survive acknowledgement).
    missing = []
    path = Path(dir_path).resolve()
    while not path.exists():
        missing.append(path)
        path = path.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _sync_directory(directory.parent)


def list_dir(dir_path: str | Path, *, with_file_types: bool = False) -> list | None:
    """List directory entries. Returns None if missing."""
    try:
        p = Path(dir_path)
        if p.exists():
            if with_file_types:
                return list(p.iterdir())
            return [entry.name for entry in p.iterdir()]
    except Exception as e:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        print(f"[methodology-agent] Failed to list {dir_path}: {e}", file=sys.stderr)
    return None


def stat_file(file_path: str | Path) -> os.stat_result | None:
    """Get file stats. Returns None if missing."""
    try:
        return Path(file_path).stat()
    except OSError:
        return None


def _sync_directory(path: Path) -> None:
    """Persist directory entries after mkdir or atomic replacement. source: ADR-1084"""
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
