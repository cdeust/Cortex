"""Restore a staged backup into a fresh Cortex root (issue #731, slice 4).

Composition root. A backup is the staging tree of ``handlers/backup_snapshot.py``
with its manifest at the top (``cortex-backup-manifest.json``).
``restore_backup`` reads that manifest, then refuses the backup before it
writes anything when:

- the manifest is absent, of another format, version or resource table
  (``core/backup_manifest.parse_manifest``), or of a managed PostgreSQL install;
- the tree does not carry exactly the manifest's files: one absent, one the
  manifest does not name, one whose digest or size differs, a required store
  absent, a symbolic link (``core/backup_verify.py`` names each);
- the SQLite store is not a database SQLite calls intact.

The target must not exist: a restore never writes over an install. The files
are copied into ``<target>.partial`` beside it, owner-only like a staging tree,
and that copy is scanned and compared with the manifest again. Only then is it
renamed to the target, so a path that exists as the target is always a verified
copy. A restore that fails after the copy began leaves ``<target>.partial``
and no target; the next attempt refuses a non-empty ``.partial``.

Only the files the manifest names are copied; the manifest itself is not: a
restored root is an install, not a backup. No tool is registered yet.

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md §5
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.core.backup_manifest import (
    MANAGED,
    MANIFEST_NAME,
    ManifestError,
    parse_manifest,
)
from mcp_server.core.backup_verify import manifest_differences
from mcp_server.handlers.backup_manifest import backup_manifest
from mcp_server.infrastructure.backup_stage import (
    copy_files,
    prepare_staging,
    private_dirs,
    read_text_file,
)
from mcp_server.infrastructure.sqlite_snapshot import check_snapshot

_SQLITE_STORE = "sqlite_store"
_PARTIAL_SUFFIX = ".partial"


class RestoreError(ValueError):
    """A backup cannot be restored as asked; the message names why."""


def _read_manifest(archive: Path) -> dict[str, Any]:
    text = read_text_file(archive, MANIFEST_NAME)
    if text is None:
        raise RestoreError(f"{archive} holds no {MANIFEST_NAME}: not a complete backup")
    manifest = parse_manifest(text)
    if manifest["backend"] == MANAGED:
        raise ManifestError(
            "a managed PostgreSQL backup cannot be restored yet (issue #731)"
        )
    return manifest


def _verify(tree: Path, manifest: dict[str, Any], what: str) -> None:
    """Refuse ``tree`` unless its scan is the manifest's entries."""
    scanned = backup_manifest(tree, manifest["backend"])
    differences = manifest_differences(manifest, scanned)
    if differences:
        raise RestoreError(
            f"{what} {tree} does not match its manifest: {'; '.join(differences)}"
        )


def _check_store(archive: Path, manifest: dict[str, Any]) -> None:
    for entry in manifest["entries"]:
        if entry["name"] == _SQLITE_STORE:
            check_snapshot(archive / entry["path"])


def _copy(archive: Path, partial: Path, manifest: dict[str, Any]) -> None:
    for entry in manifest["entries"]:
        if entry["present"] and entry["kind"] == "dir":  # an empty one too
            private_dirs(partial, entry["path"])
        paths = [file["path"] for file in entry["files"]]
        copy_files(archive, partial, paths, consumed_ok=False)


def restore_backup(archive: Path, target: Path) -> dict[str, Any]:
    """Copy the backup at ``archive`` to the new root ``target``; its manifest."""
    manifest = _read_manifest(archive)
    _verify(archive, manifest, "the backup")
    _check_store(archive, manifest)
    if target.exists() or target.is_symlink():
        raise RestoreError(f"{target} exists; a restore never writes over an install")
    partial = target.with_name(target.name + _PARTIAL_SUFFIX)
    if partial.resolve().is_relative_to(archive.resolve()):
        raise RestoreError(f"{target} is inside the backup {archive}")
    prepare_staging(archive, partial)
    _copy(archive, partial, manifest)
    _verify(partial, manifest, "the restored copy")
    partial.rename(target)
    return manifest
