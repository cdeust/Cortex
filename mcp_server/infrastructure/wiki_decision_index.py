"""Only canonical filenames define identities. No fuzzy title matching or global
wiki export is performed; every operation stays inside the supplied root.

source: ADR-0624"""

from __future__ import annotations

import re
import json
import os
import tempfile
import hashlib
import stat
from pathlib import Path

from mcp_server.shared.wiki_decision_ids import (
    decision_id,
    parse_decision_id,
    parse_decision_filename,
)

_NUMERIC_PREFIX = re.compile(r"[0-9]+(?:-|\.)")


def safe_join(root: Path, relative: str) -> Path:
    """Reject traversal and symlink escapes with stdlib-only resolution."""
    base = root.resolve()
    target = (base / relative).resolve()
    if Path(relative).is_absolute() or not target.is_relative_to(base):
        raise ValueError(f"path escapes wiki root: {relative!r}")
    return target


def _pages(root: Path) -> list[Path]:
    directory = safe_join(root, "adr")
    return sorted(directory.rglob("*.md")) if directory.exists() else []


def decision_index(root: Path | str) -> dict[str, str]:
    """Return canonical ID -> root-relative path; reject ambiguous IDs/escapes."""
    base = Path(root).resolve()
    result: dict[str, str] = {}
    for path in _pages(base):
        relative = path.relative_to(base).as_posix()
        safe_join(base, relative)
        number = parse_decision_filename(path.name)
        if number is None:
            continue
        token = decision_id(number)
        if token in result:
            raise ValueError(
                f"duplicate decision identity {token}: {result[token]}, {relative}"
            )
        result[token] = relative
    return result


def quarantine_plan(root: Path | str) -> dict[str, str]:
    """Plan malformed numeric ADR moves; nonnumeric notes remain untouched."""
    base = Path(root).resolve()
    moves: dict[str, str] = {}
    for path in _pages(base):
        relative = path.relative_to(base).as_posix()
        safe_join(base, relative)
        if (
            _NUMERIC_PREFIX.match(path.name)
            and parse_decision_filename(path.name) is None
        ):
            target = f".quarantine/{relative}"
            if safe_join(base, target).exists():
                raise ValueError(f"quarantine target already exists: {target}")
            moves[relative] = target
    return moves


def quarantine_malformed_decisions(
    root: Path | str, *, apply: bool = False
) -> dict[str, str]:
    """Default to planning; explicit apply moves original bytes without
    rewriting.

    source: ADR-0624"""
    base = Path(root).resolve()
    moves = quarantine_plan(base)
    if apply:
        for source, destination in moves.items():
            target = safe_join(base, destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            # source: ADR-0624
            with target.open("xb") as output:
                output.write(safe_join(base, source).read_bytes())
            safe_join(base, source).unlink()
    return moves


def _directory_stamp(path: Path) -> list[int]:
    """Use nanosecond identity/change stamps, not file-body timestamps.

    source: ADR-0624"""
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"ADR inventory requires real directories: {path}")
    return [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns]


def _directory_inventory(root: Path) -> dict[str, list[int]]:
    directory = root / "adr"
    if directory.is_symlink():
        raise ValueError("ADR inventory requires a real root directory")
    if not directory.exists():
        return {}
    result = {"adr": _directory_stamp(directory)}
    for current, directories, _files in os.walk(directory, followlinks=False):
        for name in sorted(directories):
            path = Path(current) / name
            result[path.relative_to(root).as_posix()] = _directory_stamp(path)
    return result


def _atomic_json(target: Path, payload: object) -> bytes:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    descriptor, name = tempfile.mkstemp(prefix=".decision-index-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return data


def write_decision_index(root: Path | str) -> dict[str, str]:
    """Persist deterministic ID map plus local directory freshness evidence.

    source: ADR-0624"""
    base = Path(root).resolve()
    before = _directory_inventory(base)
    index = decision_index(base)
    if before != _directory_inventory(base):
        raise ValueError("ADR inventory changed during indexing; retry wiki_reindex")
    data = _atomic_json(safe_join(base, ".generated/decision-index.json"), index)
    _atomic_json(
        safe_join(base, ".generated/decision-index-state.json"),
        {"sha256": hashlib.sha256(data).hexdigest(), "directories": before},
    )
    return index


def _validate_directories(base: Path, directories: object) -> None:
    if not isinstance(directories, dict):
        raise ValueError("invalid decision directory inventory")
    if not directories:
        if (base / "adr").exists() or (base / "adr").is_symlink():
            raise ValueError("decision index stale; run wiki_reindex")
        return
    if "adr" not in directories:
        raise ValueError("decision directory inventory missing ADR root")
    for relative, expected in directories.items():
        if not isinstance(relative, str):
            raise ValueError("invalid decision directory path")
        parts = Path(relative).parts
        if not parts or parts[0] != "adr" or ".." in parts:
            raise ValueError("invalid decision directory path")
        path = safe_join(base, relative)
        if (base / relative).is_symlink() or _directory_stamp(path) != expected:
            raise ValueError("decision index stale; run wiki_reindex")


def _read_index(base: Path) -> tuple[dict[str, str], dict]:
    target = safe_join(base, ".generated/decision-index.json")
    state_path = safe_join(base, ".generated/decision-index-state.json")
    if not target.is_file() or not state_path.is_file():
        raise ValueError("decision index missing; run wiki_reindex")
    data = target.read_bytes()
    persisted = json.loads(data)
    state = json.loads(state_path.read_bytes())
    if not isinstance(persisted, dict) or not isinstance(state, dict):
        raise ValueError("invalid decision index schema")
    if state.get("sha256") != hashlib.sha256(data).hexdigest():
        raise ValueError("decision index stale or modified; run wiki_reindex")
    for token, relative in persisted.items():
        number = parse_decision_id(token)
        if not isinstance(relative, str) or number is None:
            raise ValueError("invalid decision index entry")
        parts = Path(relative).parts
        if (
            not parts
            or parts[0] != "adr"
            or ".." in parts
            or parse_decision_filename(parts[-1]) != number
        ):
            raise ValueError("invalid decision index source path")
    return persisted, state


def lookup_decision(root: Path | str, token: str) -> str | None:
    """Validate directory freshness and one target without statting every page.

    Complexity is O(directory count + serialized map bytes), not one filesystem
    resolution per page. New/deleted/renamed entries invalidate parent stamps,
    including duplicate IDs in existing or newly created domain directories.
    Page text edits do not change identity and readers receive current bytes.
    """
    if parse_decision_id(token) is None:
        raise ValueError("expected a canonical ADR-NNNN token")
    base = Path(root).resolve()
    try:
        persisted, state = _read_index(base)
        _validate_directories(base, state.get("directories"))
        relative = persisted.get(token)
        if relative is not None:
            target = safe_join(base, relative)
            if (base / relative).is_symlink() or not target.is_file():
                raise ValueError("decision index target stale; run wiki_reindex")
        return relative
    except OSError as exc:
        raise ValueError(
            "decision index stale or unreadable; run wiki_reindex"
        ) from exc
