"""Build the backup manifest of one Cortex root (issue #731, slice 2).

Composition root: the resource table and the format come from
``core/backup_manifest.py``, the files are read by
``infrastructure/backup_scan.py``. No tool is registered yet; the consistent
snapshot and the restore check (later slices of #731) call this.

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.core.backup_manifest import build_manifest, resources_for
from mcp_server.infrastructure.backup_scan import scan_resource


def backup_manifest(
    root: Path, backend: str, now: datetime | None = None
) -> dict[str, Any]:
    """The manifest of ``root`` for a ``backend`` install, each file digested."""
    specs = resources_for(backend)
    scanned = {spec.name: scan_resource(root, spec.path, spec.kind) for spec in specs}
    created_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return build_manifest(backend, scanned, created_at)
