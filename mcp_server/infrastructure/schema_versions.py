"""The schema versions this code knows, and the runtime's decision on them.

Driver-free (no psycopg import), so that a process holding no database
connection, the store broker's clients (ADR-1112 decision 6) and the Codex
rebuild script, can compare schema versions; ``pg_migrations`` reads and
applies them on a connection.

source: ADR-1112
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as package_version

# source: ADR-1112 the version this code defines; bump with every DDL change
SCHEMA_VERSION = 3
# source: ADR-1112 compute_ddl_hash() of each version (v1 = main df3a4479)
SCHEMA_HASHES: dict[int, str] = {
    1: "44002703f29f0c2d8d01b5b343bf6fe5e995b989126b7b00f7e6a96474c21f87",
    # v2: backfill_log is part of the schema (ADR-1112 increment 2)
    2: "88211fbd5be16f33b6401d81b9fef8a29180eaf3ec155a8e765af7343416a3a5",
    # v3: recall_memories() sets its trigram threshold in its body, not as a
    # function SET clause a non-superuser cannot create (ADR-1112 increment 6)
    3: "a4c5fea2e4b88c0a0d64df0a250736e1b40484d57aa5b38255cf5898bb0f5ddd",
}
# source: ADR-1112 (the operator's remedy, named in every refusal)
_MIGRATE_HINT = "run 'python -m mcp_server.migrate' once"


class SchemaError(RuntimeError):
    """The database schema cannot be used by this code; nothing was changed."""


class SchemaTooNewError(SchemaError):
    """The database is at a higher version than this code: upgrade Cortex."""


class SchemaBehindError(SchemaError):
    """The database is at a lower or unknown version: run the migration step."""


class SchemaTamperedError(SchemaError):
    """``schema_meta`` was rewritten by an install that does not version."""


class MigrationFailedError(SchemaError):
    """A migration statement failed; the version was not recorded."""

    def __init__(self, message: str, failures: list[str] | None = None) -> None:
        super().__init__(message)
        self.failures = failures or []


class MigrationPrerequisiteError(SchemaError):
    """A required extension is missing and this role cannot create it; no
    statement was applied and nothing was recorded."""


@dataclass(frozen=True)
class SchemaState:
    """What the database records; ``fresh`` means no Cortex schema at all."""

    fresh: bool
    version: int | None
    recorded_hash: str | None

    @property
    def effective_version(self) -> int | None:
        """``schema_version`` if present, else the version whose fingerprint
        ``schema_meta`` records (a database migrated before ADR-1112)."""
        if self.version is not None:
            return self.version
        for number, fingerprint in SCHEMA_HASHES.items():
            if fingerprint == self.recorded_hash:
                return number
        return None


def code_revision() -> str:
    """The installed distribution version, recorded next to the schema version."""
    try:
        return package_version("hypermnesia-mcp")
    except PackageNotFoundError:
        return "source-tree"


def check_runtime(state: SchemaState) -> bool:
    """True when the schema is current; False on a first run (no schema).

    Raises a ``SchemaError`` in every other case, without touching anything."""
    if state.fresh:
        return False
    found = state.effective_version
    if found is not None and found > SCHEMA_VERSION:
        raise SchemaTooNewError(
            f"the database schema is at version {found}, newer than this Cortex "
            f"(version {SCHEMA_VERSION}); upgrade Cortex. Nothing was changed."
        )
    if found is None or found < SCHEMA_VERSION:
        label = "unknown" if found is None else found
        raise SchemaBehindError(
            f"the database schema is at version {label} "
            f"(fingerprint {str(state.recorded_hash)[:16]}), this Cortex needs "
            f"version {SCHEMA_VERSION}; {_MIGRATE_HINT}."
        )
    if state.recorded_hash != SCHEMA_HASHES[SCHEMA_VERSION]:
        raise SchemaTamperedError(
            f"schema_version says {found} but schema_meta records "
            f"{str(state.recorded_hash)[:16]}: an install that does not version its "
            "schema (an older Cortex, e.g. a Codex uv-tool wheel) re-applied its "
            "own DDL. Rebuild that install from this release "
            f"(scripts/rebuild_codex_install.py), then {_MIGRATE_HINT}."
        )
    return True
