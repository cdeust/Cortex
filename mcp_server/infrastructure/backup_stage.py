"""The staging tree a backup is taken into (issue #731, slice 3).

A backup is first a copy of the class A files of one Cortex root into a fresh
directory, the staging root; the manifest (``core/backup_manifest.py``) is then
computed on that copy, so its digests describe what the backup carries, not a
store that kept moving after it was read.

``prepare_staging`` refuses a staging root that already holds anything, or
that lies inside the Cortex root (the copy would scan itself).
``copy_files`` copies plain files by their POSIX paths relative to the root.

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md §5
"""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import Iterable


class StagingError(OSError):
    """The staging root cannot receive a backup."""


def prepare_staging(root: Path, staging: Path) -> None:
    """Create ``staging`` empty, outside ``root``; refuse it otherwise."""
    resolved_root, resolved = root.resolve(), staging.resolve()
    if resolved == resolved_root or resolved.is_relative_to(resolved_root):
        raise StagingError(f"{staging} is inside the Cortex root {root}")
    if staging.is_symlink() or (staging.exists() and not staging.is_dir()):
        raise StagingError(f"{staging} is not a directory")
    if staging.exists() and any(staging.iterdir()):
        raise StagingError(f"{staging} is not empty")
    staging.mkdir(parents=True, exist_ok=True)


def copy_files(root: Path, staging: Path, paths: Iterable[str]) -> None:
    """Copy each ``root/path`` to ``staging/path``, contents only."""
    for path in paths:
        relative = PurePosixPath(path)
        target = staging.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root.joinpath(*relative.parts), target)
