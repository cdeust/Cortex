"""Generic filesystem operations for JSON and text files.

- read_json returns parsed object or None (never throws)
- write_json creates parent directories as needed
- All text operations use UTF-8 encoding
"""

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

    Atomic: writes to a sibling temp file in the same directory, then
    ``os.replace``s it over the target — a reader (or a concurrent writer,
    e.g. two SessionStart hooks racing on mcp-connections.json) always
    sees either the old complete content or the new complete content,
    never a partially-written file. ``os.replace`` is atomic on the same
    filesystem on both POSIX and Windows. source: review round 2 finding
    (pipeline_discovery.py's config write was a plain, non-atomic
    ``p.write_text``).
    """
    p = Path(file_path)
    ensure_dir(p.parent)
    tmp = p.with_suffix(f"{p.suffix}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


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
    """Ensure a directory exists, creating it recursively if needed."""
    Path(dir_path).mkdir(parents=True, exist_ok=True)


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
