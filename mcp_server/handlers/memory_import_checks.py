"""Validation of an export file before anything from it is stored.

An export file is input from outside the store: it can be edited or written
by hand. Before the first insert, :func:`checked_records` verifies the
header and every record, and fails the whole file on the first violation
(nothing is imported from a file that holds one bad record):

- every field has its exported type (``_TEXT``, ``_NUMBERS``, ``_FLAGS``);
- every directory is the file's project root or a directory below it,
  written in canonical form (absolute, no ``.``, ``..`` or empty segment),
  so normalising cannot move it elsewhere; only a global memory of a file
  exported with ``include_global`` may come from another directory;
- each record is then moved to the target root, and the flags that change
  how a memory is shared or kept (``is_global``, ``is_protected``,
  ``is_team_decision``) are turned off unless the caller trusts them.

source: ADR-1113 (review of PR #775, B2)"""

from __future__ import annotations

import math
import os
import posixpath
from datetime import datetime
from typing import Any

# source: ADR-1113 — the exported types of EXPORT_FIELDS
_TEXT = (
    "domain",
    "source",
    "store_type",
    "agent_context",
    "write_class",
    "capture_origin",
    "source_attribution",
)
_NUMBERS = ("importance", "emotional_valence", "confidence")
_FLAGS = ("is_global", "is_protected", "is_team_decision")


def canonical_root(path: str) -> str:
    """Absolute, normalised, slash-separated, symlinks kept."""
    absolute = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
    return absolute.replace("\\", "/").rstrip("/") or "/"


def _is_canonical(path: str) -> bool:
    return posixpath.normpath(path) == path and path not in ("", ".")


def _within(directory: str, root: str) -> bool:
    return directory == root or directory.startswith(root.rstrip("/") + "/")


def _check_header(header: dict[str, Any], fields: tuple[str, ...]) -> str:
    root = header.get("project_root")
    if not isinstance(root, str) or canonical_root(root) != root:
        raise ValueError(f"header project_root {root!r} is not a canonical path")
    if not isinstance(header.get("include_global"), bool):
        raise ValueError("header include_global is not a boolean")
    if header.get("fields") != list(fields):
        raise ValueError("header fields differ from this version's fields")
    return root


def _check_types(record: dict[str, Any]) -> None:
    content = record.get("content")
    if not isinstance(content, str) or not content:
        raise ValueError("a record's content is not a non-empty string")
    tags = record.get("tags")
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("a record's tags are not a list of strings")
    for field in _TEXT:
        if record.get(field) is not None and not isinstance(record[field], str):
            raise ValueError(f"a record's {field} is not a string")
    for field in _NUMBERS:
        value = record.get(field)
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if value is not None and not (number and math.isfinite(value)):
            raise ValueError(f"a record's {field} is not a finite number")
    for field in _FLAGS:
        if record.get(field) is not None and not isinstance(record[field], bool):
            raise ValueError(f"a record's {field} is not a boolean")
    created = record.get("created_at")
    if created is not None:
        if not isinstance(created, str):
            raise ValueError("a record's created_at is not a string")
        datetime.fromisoformat(created)  # ValueError when it is not ISO 8601


def _confined(record: dict[str, Any], root: str, include_global: bool) -> str:
    """The record's directory relative to ``root``; '' for the root itself."""
    directory = record.get("directory_context")
    if record.get("is_global") is True and include_global:
        if isinstance(directory, str) and _is_canonical(directory):
            if _within(directory, root):
                return directory[len(root.rstrip("/")) :]
        return ""
    if not isinstance(directory, str) or not _is_canonical(directory):
        raise ValueError(f"record directory {directory!r} is outside {root}")
    if not _within(directory, root):
        raise ValueError(f"record directory {directory!r} is outside {root}")
    return directory[len(root.rstrip("/")) :]


def checked_records(
    header: dict[str, Any],
    records: list[dict[str, Any]],
    fields: tuple[str, ...],
    *,
    into_project_root: str | None,
    trust_flags: bool,
) -> list[dict[str, Any]]:
    """Validated, confined copies of ``records``; ValueError on any violation."""
    root = _check_header(header, fields)
    target = canonical_root(into_project_root) if into_project_root else root
    include_global = header["include_global"]
    out = []
    for record in records:
        _check_types(record)
        relative = _confined(record, root, include_global)
        data = {k: v for k, v in record.items() if v is not None}
        data["directory_context"] = target.rstrip("/") + relative or "/"
        for flag in _FLAGS:
            data[flag] = bool(record.get(flag)) and trust_flags
        out.append(data)
    return out
