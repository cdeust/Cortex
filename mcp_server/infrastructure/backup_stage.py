"""The staging tree a backup is taken into (issue #731, slice 3).

A backup is first a copy of the class A files of one Cortex root into a fresh
directory, the staging root; the manifest (``core/backup_manifest.py``) is then
computed on that copy, so its digests describe what the backup carries, not a
store that kept moving after it was read.

The copy is personal data, so it follows ADR-1112 like its sources: every
directory of the staging tree is created ``0o700`` and every file ``0o600``,
whatever the umask. A file is created with ``O_CREAT|O_EXCL|O_NOFOLLOW``, so
the copy never writes through a link nor over an existing entry.

``prepare_staging`` refuses a staging root that already holds anything, or
that lies inside the Cortex root (the copy would scan itself).
``private_dirs`` creates the directories of a relative POSIX path;
``copy_files`` copies plain files by their POSIX paths relative to the root.
``write_new_file`` and ``read_text_file`` write and read one file at the top of
a tree: the manifest of a staged backup (slice 4).

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md §5;
ADR-1112 (``shared/private_paths.py``)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

from mcp_server.shared.private_paths import PRIVATE_DIR_MODE, PRIVATE_FILE_MODE

# source: ADR-1112 — refuse a link and an existing entry; binary on Windows
_CREATE = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)
)


def _new_private_file(path: Path) -> BinaryIO:
    """Open the new ``0o600`` file ``path`` for writing, never through a link.

    The one write site of this module, audited in
    ``tests_py/architecture/test_storage_redaction_gate.py`` (ADR-1110).
    """
    return os.fdopen(os.open(path, _CREATE, PRIVATE_FILE_MODE), "wb")


class StagingError(OSError):
    """The staging root cannot receive a backup."""


def prepare_staging(root: Path, staging: Path) -> None:
    """Create ``staging`` empty and owner-only, outside ``root``; refuse otherwise."""
    resolved_root, resolved = root.resolve(), staging.resolve()
    if resolved == resolved_root or resolved.is_relative_to(resolved_root):
        raise StagingError(f"{staging} is inside the Cortex root {root}")
    if staging.is_symlink() or (staging.exists() and not staging.is_dir()):
        raise StagingError(f"{staging} is not a directory")
    if staging.exists() and any(staging.iterdir()):
        raise StagingError(f"{staging} is not empty")
    staging.parent.mkdir(parents=True, exist_ok=True)
    if not staging.exists():
        staging.mkdir(mode=PRIVATE_DIR_MODE)
    staging.chmod(PRIVATE_DIR_MODE)  # an empty directory given by the caller


def private_dirs(staging: Path, relative: str) -> Path:
    """Create ``staging/relative`` level by level, each new level ``0o700``."""
    current = staging
    for part in PurePosixPath(relative).parts:
        current = current / part
        if not current.is_dir() or current.is_symlink():
            current.mkdir(mode=PRIVATE_DIR_MODE)
    return current


def copy_files(
    root: Path, staging: Path, paths: Iterable[str], *, consumed_ok: bool
) -> None:
    """Copy each ``root/path`` to a new ``0o600`` file ``staging/path``.

    ``consumed_ok`` lets a file that vanished after it was listed be left out;
    any other missing file is an error.
    """
    for path in paths:
        relative = PurePosixPath(path)
        try:
            source = root.joinpath(*relative.parts).open("rb")
        except FileNotFoundError:
            if consumed_ok:
                continue
            raise
        target = private_dirs(staging, relative.parent.as_posix()) / relative.name
        with source, _new_private_file(target) as out:
            shutil.copyfileobj(source, out)


def write_new_file(directory: Path, name: str, data: bytes) -> None:
    """Write ``data`` to the new ``0o600`` file ``directory/name``, never over one."""
    with _new_private_file(directory / name) as out:
        out.write(data)


def read_text_file(directory: Path, name: str) -> str | None:
    """The text of the plain file ``directory/name``; ``None`` when it is not one.

    A byte that is not UTF-8 is replaced, so the reader's parser refuses the
    text instead of this function raising a decoding error.
    """
    path = directory / name
    if path.is_symlink() or not path.is_file():
        return None
    return path.read_bytes().decode(errors="replace")  # UTF-8, bytes.decode default
