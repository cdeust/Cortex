"""Backups built for the restore tests (issue #731, slice 4)."""

from __future__ import annotations

from mcp_server.core.backup_manifest import MANIFEST_NAME, to_json
from mcp_server.handlers.backup_manifest import backup_manifest
from mcp_server.handlers.backup_snapshot import snapshot_backup

PAGE = "methodology/wiki/adr/1.md"


def write(root, relative: str, data: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def files_backup(tmp_path):
    """A postgresql-backend backup: files only, one wiki page, empty artifacts."""
    root, archive = tmp_path / "root", tmp_path / "backup"
    write(root, PAGE, b"page")
    (root / "methodology" / "artifacts").mkdir()
    snapshot_backup(root, archive, "postgresql")
    return archive


def hand_made_backup(archive, backend: str) -> None:
    """Give the files already under ``archive`` the manifest that describes them."""
    text = to_json(backup_manifest(archive, backend))
    (archive / MANIFEST_NAME).write_text(text, encoding="ascii")


def tree(root) -> dict[str, bytes | None]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None
        for p in sorted(root.rglob("*"))
    }
