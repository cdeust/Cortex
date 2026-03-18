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
    except Exception as e:
        print(f"[methodology-agent] Failed to read {file_path}: {e}", file=sys.stderr)
    return None


def write_json(file_path: str | Path, data: Any) -> None:
    """Write an object as JSON, creating parent directories as needed."""
    p = Path(file_path)
    ensure_dir(p.parent)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_text_file(file_path: str | Path) -> str | None:
    """Read a text file. Returns None if missing."""
    try:
        p = Path(file_path)
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception as e:
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
    except Exception as e:
        print(f"[methodology-agent] Failed to list {dir_path}: {e}", file=sys.stderr)
    return None


def stat_file(file_path: str | Path) -> os.stat_result | None:
    """Get file stats. Returns None if missing."""
    try:
        return Path(file_path).stat()
    except Exception:
        return None
