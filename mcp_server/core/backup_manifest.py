"""The versioned manifest of a Cortex backup (issue #731, slice 2).

A manifest names the class A resources of one install (user data that cannot be
rebuilt) and gives a SHA-256 digest and a size for every file it carries. The
resource table is the class A set of
``docs/audits/owned-resources-backup-2026-11-05.md`` §2-3, by backend:

- every backend: backend marker, wiki pages, raw-output artifacts, MCP
  connection list, cognitive profiles (``domains/``, ``index.json``, legacy
  ``profiles.json*``), session log, capture spool;
- ``sqlite``: ``methodology/memory.db`` (required);
- ``managed``: the plugin-managed cluster and its password (both required; the
  password is marked ``secret``);
- ``postgresql``: nothing more, the server is the user's (class X).

Paths are POSIX strings relative to the Cortex root (``~/.claude`` or
``CORTEX_CLAUDE_DIR``). A store relocated outside the root
(``CORTEX_MEMORY_DB_PATH``) is therefore absent, and a required absent resource
is refused, never silently omitted. The SQLite ``-wal``/``-shm`` files are not
entries: a backup carries one consistent copy of the database (slice 3), and the
manifest describes the tree it is given.

Pure: the files are read and hashed by ``infrastructure/backup_scan.py``.

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

FORMAT = "cortex-backup-manifest"
# source: issue #731 slice 2, the first format; bump on any change to the
# resource table or to the entry and file fields below.
VERSION = 1

SQLITE = "sqlite"
MANAGED = "managed"
POSTGRESQL = "postgresql"
# The marker values of infrastructure/backend_marker.py MARKER_BACKENDS.
BACKENDS = frozenset({SQLITE, MANAGED, POSTGRESQL})

FileRecord = tuple[str, str, int]  # (path relative to the root, sha256 hex, size)

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class ManifestError(ValueError):
    """A manifest cannot be built or read as asked; the message names why."""


@dataclass(frozen=True)
class ResourceSpec:
    """One class A resource: where it lives under the root and for which backends."""

    name: str
    path: str
    kind: str  # "file" or "dir"
    backends: frozenset[str]
    required: bool
    secret: bool = False


RESOURCES: tuple[ResourceSpec, ...] = (
    ResourceSpec(
        "sqlite_store", "methodology/memory.db", "file", frozenset({SQLITE}), True
    ),
    ResourceSpec(
        "managed_cluster",
        "methodology/managed-pg/cluster",
        "dir",
        frozenset({MANAGED}),
        True,
    ),
    ResourceSpec(
        "managed_password",
        "methodology/managed-pg/password",
        "file",
        frozenset({MANAGED}),
        True,
        secret=True,
    ),
    ResourceSpec("backend_marker", "methodology/backend.json", "file", BACKENDS, False),
    ResourceSpec("wiki", "methodology/wiki", "dir", BACKENDS, False),
    ResourceSpec("artifacts", "methodology/artifacts", "dir", BACKENDS, False),
    ResourceSpec(
        "mcp_connections", "methodology/mcp-connections.json", "file", BACKENDS, False
    ),
    ResourceSpec("profile_domains", "methodology/domains", "dir", BACKENDS, False),
    ResourceSpec("profile_index", "methodology/index.json", "file", BACKENDS, False),
    ResourceSpec(
        "legacy_profiles", "methodology/profiles.json", "file", BACKENDS, False
    ),
    ResourceSpec(
        "legacy_profiles_backup",
        "methodology/profiles.json.v1_backup",
        "file",
        BACKENDS,
        False,
    ),
    ResourceSpec(
        "session_log", "methodology/session-log.json", "file", BACKENDS, False
    ),
    ResourceSpec("capture_spool", ".capture-worker/spool", "dir", BACKENDS, False),
)


def resources_for(backend: str) -> tuple[ResourceSpec, ...]:
    """The class A resources a ``backend`` install carries, in table order."""
    if backend not in BACKENDS:
        raise ManifestError(
            f"unknown backend {backend!r}; expected one of {sorted(BACKENDS)}"
        )
    return tuple(spec for spec in RESOURCES if backend in spec.backends)


def _checked_files(
    spec: ResourceSpec, records: Sequence[FileRecord]
) -> list[dict[str, Any]]:
    """One resource's records as manifest files: sorted, each inside it."""
    if spec.kind == "file" and [r[0] for r in records] != [spec.path]:
        raise ManifestError(f"{spec.path} is a file resource: one record, its own path")
    files = []
    for path, sha256, size in sorted(records):
        if spec.kind == "dir" and not path.startswith(spec.path + "/"):
            raise ManifestError(f"{path} is not inside {spec.path}")
        if not _SHA256_HEX.fullmatch(sha256) or size < 0:
            raise ManifestError(f"{path}: invalid digest or size")
        files.append({"path": path, "sha256": sha256, "size": size})
    return files


def _entry(
    spec: ResourceSpec, records: Sequence[FileRecord] | None, backend: str
) -> dict:
    if records is None and spec.required:
        raise ManifestError(
            f"{spec.path} is required for a {backend} backup and is absent"
        )
    return {
        "name": spec.name,
        "path": spec.path,
        "kind": spec.kind,
        "secret": spec.secret,
        "present": records is not None,
        "files": [] if records is None else _checked_files(spec, records),
    }


def build_manifest(
    backend: str,
    scanned: Mapping[str, Sequence[FileRecord] | None],
    created_at: str,
) -> dict[str, Any]:
    """The manifest of one install from its scan.

    ``scanned`` maps every resource name of ``resources_for(backend)`` to its
    file records, or to ``None`` when the resource is absent; a missing or an
    extra name is refused, so a scan cannot leave a resource out unnoticed.
    """
    specs = resources_for(backend)
    expected = {spec.name for spec in specs}
    if set(scanned) != expected:
        raise ManifestError(
            f"scan names {sorted(set(scanned))}, "
            f"the {backend} table names {sorted(expected)}"
        )
    return {
        "format": FORMAT,
        "version": VERSION,
        "created_at": created_at,
        "backend": backend,
        "entries": [_entry(spec, scanned[spec.name], backend) for spec in specs],
    }


def to_json(manifest: Mapping[str, Any]) -> str:
    """Canonical text: ASCII, sorted keys, two-space indent, one trailing newline."""
    return json.dumps(manifest, sort_keys=True, indent=2) + "\n"


def parse_manifest(text: str) -> dict[str, Any]:
    """Read a manifest; refuse another format, another version or another table."""
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"not JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ManifestError(f"not a {FORMAT} document")
    if manifest.get("version") != VERSION:
        raise ManifestError(
            f"manifest version {manifest.get('version')!r}, this Cortex reads {VERSION}"
        )
    specs = resources_for(manifest.get("backend"))
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise ManifestError("entries must be a list of objects")
    names = [entry.get("name") for entry in entries]
    if names != [spec.name for spec in specs]:
        raise ManifestError(
            f"entries {names} do not match the {manifest['backend']} table"
        )
    for index, spec in enumerate(specs):  # same length: the names matched above
        _check_entry(spec, entries[index], manifest["backend"])
    return manifest


def _is_record(record: tuple[Any, Any, Any]) -> bool:
    path, sha256, size = record
    return isinstance(path, str) and isinstance(sha256, str) and type(size) is int


def _check_entry(spec: ResourceSpec, entry: dict[str, Any], backend: str) -> None:
    """Refuse an entry that is not exactly what its spec and its own files build."""
    files, present = entry.get("files"), entry.get("present")
    if not isinstance(present, bool) or not isinstance(files, list):
        raise ManifestError(f"entry {spec.name}: present or files malformed")
    if not all(isinstance(f, dict) for f in files):
        raise ManifestError(f"entry {spec.name}: present or files malformed")
    records = [(f.get("path"), f.get("sha256"), f.get("size")) for f in files]
    if not all(_is_record(record) for record in records):
        raise ManifestError(f"entry {spec.name}: present or files malformed")
    if _entry(spec, records if present else None, backend) != entry:
        raise ManifestError(f"entry {spec.name} differs from the table or its files")
