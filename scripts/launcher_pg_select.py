"""Whether Setup may select the plugin's managed PostgreSQL for this store.

Selection order (ADR-1110, amending ADR-1104 decision 1):

1. A configured database (``database_url`` — ``DATABASE_URL`` or, for hooks,
   ``CLAUDE_PLUGIN_OPTION_DATABASE_URL`` mapped onto it — or any explicit
   ``CORTEX_*`` backend setting) always wins: nothing managed is started.
2. The backend marker ``{"backend": "managed", "root": ...}`` selects the
   managed server. Only Setup writes it, and only after the server started and
   ``vector``, ``pg_trgm`` and the schema were created (``launcher_pg_provision``).
3. Otherwise ADR-1104 as before: the marker, or the first-launch decision
   (SQLite for a fresh install), with SQLite as the default.

Attaching a launch to the selected server is ``backend_marker``'s job (in the
wheel, so Codex and direct launches attach the same way, ADR-1110 D1).

A store is *eligible* for the managed server when nothing configures one and
no store exists yet: no marker and no earlier Cortex state, or the launcher's
own first-launch SQLite marker with no SQLite file at the engine's path
(``CORTEX_MEMORY_DB_PATH`` honoured). Nothing is migrated here: an existing
SQLite store keeps its marker, which a later importer flips to ``managed``.

source: ADR-1110
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

WRITTEN_BY = "Setup (managed PostgreSQL started, ADR-1110)"  # source: ADR-1110
# source: memory_config.MemorySettings DB_PATH and SQLITE_FALLBACK_PATH
# (env_prefix CORTEX_MEMORY_)
_DB_PATH_ENVS = ("CORTEX_MEMORY_DB_PATH", "CORTEX_MEMORY_SQLITE_FALLBACK_PATH")


def sqlite_store_paths(environ: Mapping[str, str], methodology_dir: Path) -> list[Path]:
    """Where the engine may keep the SQLite store: ``MemorySettings.DB_PATH``
    and ``SQLITE_FALLBACK_PATH`` (memory_store uses the latter for an empty path)."""
    default = methodology_dir / "memory.db"
    return [
        Path(configured).expanduser() if configured else default
        for configured in (environ.get(name, "").strip() for name in _DB_PATH_ENVS)
    ]


def why_not_eligible(
    environ: Mapping[str, str], marker: dict | None, marker_path: Path
) -> str:
    """``""`` when a new managed store may be selected, else the reason it may not."""
    import launcher_backend  # noqa: PLC0415 — launcher_backend imports this module
    from mcp_server.infrastructure.backend_marker import environment_decides  # noqa: PLC0415 — resolvable once plugin_root is on sys.path

    configured = dict(environ)
    launcher_backend.map_database_option(configured)
    if environment_decides(configured):
        return "database_url or a CORTEX_* backend setting selects the store"
    if marker is None:
        if launcher_backend.has_earlier_state(marker_path.parent, marker_path.name):
            return f"{marker_path.parent} holds earlier Cortex state"
    elif (
        marker.get("backend") != "sqlite"
        or marker.get("written_by") != launcher_backend.WRITTEN_BY
    ):
        backend, by = marker.get("backend"), marker.get("written_by")
        return f"{marker_path} selects {backend} ({by})"
    for store in sqlite_store_paths(environ, marker_path.parent):
        if store.exists():
            return (
                f"a SQLite store exists at {store}; it is not migrated by this release"
            )
    return ""
