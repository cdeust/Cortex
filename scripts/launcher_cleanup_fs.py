"""Stdlib, descriptor-bound filesystem access for explicit deps cleanup.

Sources: https://docs.python.org/3/library/os.html#files-and-directories
and https://docs.python.org/3/library/shutil.html#shutil.rmtree.
Every ancestor is opened with O_NOFOLLOW; removal never receives an absolute
path. Unsupported platforms fail closed, without changing normal launching.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class CleanupRefusedError(ValueError):
    """The filesystem or registry cannot establish safe cleanup conditions."""


def require_directory_support() -> None:
    """Refuse platforms without descriptor-relative, no-follow access."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise CleanupRefusedError("no-follow directory access is unavailable")
    if os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd:
        raise CleanupRefusedError("descriptor-relative directory access is unavailable")


@contextmanager
def directory(path: Path) -> Iterator[int]:
    """Open an absolute directory without following any ancestor symlink."""
    require_directory_support()
    if not path.is_absolute() or ".." in path.parts:
        raise CleanupRefusedError(f"expected absolute path without '..': {path}")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Do not let duplicate JSON keys hide protected plugin references."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CleanupRefusedError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_object(path: Path) -> dict[str, object]:
    """Read a regular JSON file; reject links, FIFOs and duplicate keys."""
    with directory(path.parent) as parent:
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise CleanupRefusedError(f"registry is not a regular file: {path}")
            result = json.load(stream, object_pairs_hook=_unique_pairs)
    if not isinstance(result, dict):
        raise CleanupRefusedError(f"registry is not an object: {path}")
    return result


def child_names(path: Path) -> list[str]:
    """List only one level: startup audits never traverse installed deps."""
    with directory(path) as descriptor:
        names = os.listdir(descriptor)
        return sorted(
            name
            for name in names
            if not stat.S_ISREG(
                os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode
            )
        )


def _raise_walk_error(error: OSError) -> None:
    raise error


def _check_tree(parent: int) -> None:
    """Reject existing symlinks throughout a selected dependency tree."""
    for root, dirs, files, descriptor in os.fwalk(
        "deps", dir_fd=parent, follow_symlinks=False, onerror=_raise_walk_error
    ):
        for name in dirs + files:
            mode = os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise CleanupRefusedError(
                    f"symlink or special file in dependency tree: {root}/{name}"
                )


def _has_deps(parent: int) -> bool:
    """An absent deps child is preserved; a non-directory child is refused."""
    try:
        mode = os.stat("deps", dir_fd=parent, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(mode):
        raise CleanupRefusedError("deps is a symlink or is not a directory")
    return True


def inspect_deps(path: Path, *, recursive: bool = False) -> bool:
    """Inspect only the deps child of an already constrained identity path."""
    with directory(path.parent) as parent:
        if not _has_deps(parent):
            return False
        if recursive:
            _check_tree(parent)
        return True


def require_removal_support() -> None:
    """Python 3.10 can audit, but rmtree's dir_fd requires Python 3.11+."""
    # Capability checks follow the documented API, including vendor runtimes.
    if "dir_fd" not in inspect.signature(shutil.rmtree).parameters:
        raise CleanupRefusedError(
            "safe removal requires rmtree(dir_fd=...), added in Python 3.11"
        )
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        raise CleanupRefusedError("symlink-resistant rmtree is unavailable")


def remove_deps(path: Path) -> None:
    """Delete deps only, retaining its parent and all sibling user data."""
    require_removal_support()
    with directory(path.parent) as parent:
        if not _has_deps(parent):
            raise CleanupRefusedError(
                f"dependency tree disappeared before removal: {path}"
            )
        _check_tree(parent)
        shutil.rmtree("deps", dir_fd=parent)
