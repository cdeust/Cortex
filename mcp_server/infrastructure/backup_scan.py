"""Read the files of one backup resource and digest each (issue #731, slice 2).

``scan_resource`` returns the ``(path, sha256, size)`` records the pure manifest
(``core/backup_manifest.py``) is built from, paths POSIX and relative to the
root. A resource that does not exist is ``None``. A symbolic link, or anything
that is neither a regular file nor a directory, is refused: following a link
would digest data outside the root, and skipping it would leave a file out of
the backup unnoticed.

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath


class BackupScanError(OSError):
    """A resource holds something a backup cannot carry as a plain file."""


def _record(root: Path, path: Path) -> tuple[str, str, int]:
    with path.open("rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        digest = hashlib.file_digest(handle, hashlib.sha256).hexdigest()
    return path.relative_to(root).as_posix(), digest, size


def _checked_mode(path: Path) -> int:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        raise BackupScanError(
            f"{path} is a symbolic link; a backup does not follow links"
        )
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise BackupScanError(f"{path} is neither a regular file nor a directory")
    return mode


def _walk(root: Path, directory: Path) -> list[tuple[str, str, int]]:
    records = []
    for child in sorted(directory.iterdir()):
        if stat.S_ISDIR(_checked_mode(child)):
            records.extend(_walk(root, child))
        else:
            records.append(_record(root, child))
    return records


def _check_ancestors(root: Path, relative: str) -> None:
    """Refuse a directory between ``root`` and the resource that is not a real one.

    A linked ``methodology`` would otherwise digest a store outside the root
    under a name inside it. The walk stops at the first one that is absent.
    """
    current = root
    for part in PurePosixPath(relative).parts[:-1]:
        current = current / part
        if not current.exists() and not current.is_symlink():
            return
        if not stat.S_ISDIR(_checked_mode(current)):
            raise BackupScanError(f"{current} is expected to be a dir")


def scan_resource(
    root: Path, relative: str, kind: str
) -> list[tuple[str, str, int]] | None:
    """The records of ``root/relative``; ``None`` when it does not exist.

    ``kind`` is ``"file"`` or ``"dir"``; a resource of the other kind is refused.
    """
    _check_ancestors(root, relative)
    target = root / relative
    if not target.exists() and not target.is_symlink():
        return None
    is_dir = stat.S_ISDIR(_checked_mode(target))
    if is_dir != (kind == "dir"):
        raise BackupScanError(f"{target} is expected to be a {kind}")
    return _walk(root, target) if is_dir else [_record(root, target)]
