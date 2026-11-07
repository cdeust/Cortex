"""Export and import one project's memories (GDPR art. 20 portability).

Format: JSON Lines, UTF-8. Line 1 is a header::

    {"format": "cortex-memory-export", "version": 1, "exported_at": ISO-8601,
     "project_root": str, "include_global": bool, "count": int,
     "fields": [...]}

then one object per memory with exactly the ``fields`` keys (``EXPORT_FIELDS``).
Exported are the memories the user wrote or captured for the project: its
current versions (supersession chain heads) whose ``directory_context`` is the
project root or a directory below it, plus global memories when asked.
Computed state (heat, decay, embeddings, consolidation stage) is not personal
data the user provided and is recomputed on import.

Every exported text passes the redaction gate (ADR-1110), so a secret stored
before the gate existed leaves the store redacted. The file is written
``0600``. Import writes through the store, hence through the gate again,
computes each embedding, can move the memories to another project root, and
skips a memory already present with the same content and directory, so
importing a file twice adds nothing. A file is validated as a whole before
the first insert: field types, every directory inside the file's project
root, and the sharing flags off unless trusted (``memory_import_checks``).

source: ADR-1113"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.handlers.memory_import_checks import canonical_root, checked_records
from mcp_server.infrastructure.embedding_engine import get_embedding_engine
from mcp_server.shared import gated_files
from mcp_server.shared.redaction_gate import redact_value

FORMAT = "cortex-memory-export"
VERSION = 1  # source: ADR-1113 — bump on any change to EXPORT_FIELDS
EXPORT_FIELDS = (
    "content",
    "tags",
    "domain",
    "directory_context",
    "source",
    "created_at",
    "importance",
    "emotional_valence",
    "is_global",
    "is_protected",
    "is_team_decision",
    "store_type",
    "agent_context",
    "write_class",
    "capture_origin",
    "source_attribution",
    "confidence",
)
_EXPORT_MODE = 0o600  # source: ADR-1112 (personal data, owner-only)


def _normalise_root(project_root: str) -> str:
    """Absolute and slash-normalised, symlinks kept: memories store the
    directory as it was given (``shared/project_scope.py``)."""
    return canonical_root(project_root)


def select_project_memories(
    store: Any, project_root: str, include_global: bool
) -> list[dict[str, Any]]:
    """Current memories of ``project_root`` (and below), oldest first."""
    root = _normalise_root(project_root)
    below = root.rstrip("/") + "/"
    columns = ", ".join(EXPORT_FIELDS)
    # An exact, case-sensitive prefix on both backends: SQLite's LIKE folds
    # ASCII case, so a sibling differing by case only would match.
    # source: ADR-1113 (review of PR #775, N7)
    scope = "directory_context = %s OR substr(directory_context, 1, %s) = %s"
    if include_global:
        scope += " OR is_global"
    rows = store._conn.execute(
        f"SELECT {columns} FROM memories "  # noqa: S608 — fixed column list
        f"WHERE superseded_by_id IS NULL AND ({scope}) ORDER BY created_at, id",
        (root, len(below), below),
    ).fetchall()
    return [_portable(dict(row)) for row in rows]


def _portable(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in EXPORT_FIELDS:
        value = row.get(field)
        if field == "tags" and isinstance(value, str):
            value = json.loads(value or "[]")
        if isinstance(value, datetime):
            value = value.astimezone(timezone.utc).isoformat()
        if field in ("is_global", "is_protected", "is_team_decision"):
            value = bool(value)
        out[field] = value
    return redact_value(out)


def export_project(
    store: Any, project_root: str, out_path: str | Path, *, include_global: bool = False
) -> dict[str, Any]:
    """Write the project's memories to ``out_path``; return the header."""
    records = select_project_memories(store, project_root, include_global)
    header = {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "project_root": _normalise_root(project_root),
        "include_global": include_global,
        "count": len(records),
        "fields": list(EXPORT_FIELDS),
    }
    lines = [json.dumps(header, ensure_ascii=False)]
    lines += [json.dumps(r, ensure_ascii=False, default=str) for r in records]
    gated_files.write_text(out_path, "\n".join(lines) + "\n", mode=_EXPORT_MODE)
    return header


def read_export(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse and validate an export file; raise ValueError when it is not one."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path}: empty file, not a {FORMAT}")
    header = json.loads(lines[0])
    if header.get("format") != FORMAT or header.get("version") != VERSION:
        raise ValueError(f"{path}: not a {FORMAT} version {VERSION} file")
    records = [json.loads(line) for line in lines[1:] if line.strip()]
    if len(records) != header.get("count"):
        raise ValueError(
            f"{path}: header says {header.get('count')}, file has {len(records)}"
        )
    for record in records:
        if set(record) != set(header["fields"]) or "content" not in record:
            raise ValueError(f"{path}: a record does not carry the header's fields")
    return header, records


def _already_present(store: Any, content: str, directory: str | None) -> bool:
    row = store._conn.execute(
        "SELECT id FROM memories WHERE content = %s AND directory_context = %s",
        (content, directory or ""),
    ).fetchone()
    return row is not None


def import_export(
    store: Any,
    path: str | Path,
    *,
    into_project_root: str | None = None,
    trust_flags: bool = False,
) -> dict[str, int]:
    """Insert the file's memories; return ``{"imported": n, "skipped": m}``.

    The whole file is validated first (``memory_import_checks``): a record
    of the wrong type or outside the file's project root fails the import
    before anything is stored. ``trust_flags`` keeps ``is_global``,
    ``is_protected`` and ``is_team_decision`` as the file states them."""
    header, records = read_export(path)
    checked = checked_records(
        header,
        redact_value(records),
        EXPORT_FIELDS,
        into_project_root=into_project_root,
        trust_flags=trust_flags,
    )
    engine = get_embedding_engine()
    imported = skipped = 0
    for data in checked:
        if _already_present(store, data["content"], data["directory_context"]):
            skipped += 1
            continue
        data["embedding"] = engine.encode(data["content"])
        store.insert_memory(data)
        imported += 1
    return {"imported": imported, "skipped": skipped}
