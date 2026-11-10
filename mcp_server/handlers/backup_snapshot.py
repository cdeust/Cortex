"""Take a consistent backup of one Cortex root into a staging tree (#731, slice 3).

Composition root. Every class A resource of ``core/backup_manifest.py`` is
copied from ``root`` into a fresh ``staging`` directory; the SQLite store is
copied by the online backup API (``infrastructure/sqlite_snapshot.py``), so
writes by a running server during the copy cannot tear it. The manifest is then
computed on the staging tree and returned.

The SQLite store is copied last. The capture drainer stores a spooled payload
and then deletes its spool file (``hooks/capture_drain.py``): copied after the
store, a payload pending when the backup started could be drained in between
and be in neither copy. Copied before, it is in the staged spool, and also in
the store if it was drained meanwhile, a replay the write gate absorbs.

The managed PostgreSQL cluster is refused here: a running cluster directory is
not consistent as copied files, and its stopped copy or logical dump is a later
part of this slice. No tool is registered yet; the restore check (slice 4 of
#731) consumes the staging tree.

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md §3, §5
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from mcp_server.core.backup_manifest import (
    MANAGED,
    ManifestError,
    ResourceSpec,
    resources_for,
)
from mcp_server.handlers.backup_manifest import backup_manifest
from mcp_server.infrastructure.backup_scan import scan_resource
from mcp_server.infrastructure.backup_stage import (
    copy_files,
    prepare_staging,
    private_dirs,
)
from mcp_server.infrastructure.sqlite_snapshot import snapshot_sqlite

_SQLITE_STORE = "sqlite_store"


def _stage_sqlite(root: Path, staging: Path, relative: str) -> None:
    """Snapshot the store; ``scan_resource`` first refuses a link on its path."""
    if scan_resource(root, relative, "file") is None:
        raise ManifestError(f"{relative} is required for a sqlite backup and is absent")
    parent = private_dirs(staging, PurePosixPath(relative).parent.as_posix())
    snapshot_sqlite(root / relative, parent / PurePosixPath(relative).name)


def _stage_files(root: Path, staging: Path, spec: ResourceSpec) -> None:
    records = scan_resource(root, spec.path, spec.kind)
    if records is None:
        return
    if spec.kind == "dir":  # an empty directory is still present
        private_dirs(staging, spec.path)
    copy_files(root, staging, [record[0] for record in records])


def snapshot_backup(
    root: Path, staging: Path, backend: str, now: datetime | None = None
) -> dict[str, Any]:
    """Copy the class A data of ``root`` into ``staging``; its manifest."""
    if backend == MANAGED:
        raise ManifestError(
            "a managed PostgreSQL backup needs a stopped copy or a logical dump, "
            "not implemented yet (issue #731)"
        )
    specs = resources_for(backend)
    prepare_staging(root, staging)
    for spec in specs:
        if spec.name != _SQLITE_STORE:
            _stage_files(root, staging, spec)
    for spec in specs:
        if spec.name == _SQLITE_STORE:  # last: see the module docstring
            _stage_sqlite(root, staging, spec.path)
    return backup_manifest(staging, backend, now=now)
