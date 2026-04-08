"""Memory store factory — runtime-aware backend selection.

CLI mode: PostgreSQL required, no silent fallback.
Cowork mode: tries PostgreSQL, falls back to SQLite.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _try_pg(database_url: str):
    """Try connecting to PostgreSQL. Returns PgMemoryStore or None."""
    store, _ = _try_pg_verbose(database_url)
    return store


def _try_pg_verbose(database_url: str):
    """Try connecting to PostgreSQL. Returns (store, error_message)."""
    try:
        import psycopg  # noqa: F401

        from mcp_server.infrastructure.pg_store import PgMemoryStore

        return PgMemoryStore(database_url=database_url), None
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        logger.warning("PostgreSQL unavailable (%s), falling back to SQLite", msg)
        return None, msg


class MemoryStore:
    """Runtime-aware store factory.

    CLI mode: PostgreSQL required (auto → postgresql). Raises on failure.
    Cowork mode: tries PostgreSQL, falls back to SQLite.
    Explicit sqlite backend always works (for testing).
    """

    def __new__(
        cls,
        db_path: str = "",
        embedding_dim: int = 384,
        *,
        database_url: str | None = None,
    ):
        from mcp_server.infrastructure.memory_config import get_memory_settings

        settings = get_memory_settings()
        runtime = settings.RUNTIME
        backend = settings.STORE_BACKEND
        url = (
            database_url or os.environ.get("DATABASE_URL", "") or settings.DATABASE_URL
        )

        # In CLI mode, "auto" means PostgreSQL is required
        if runtime == "cli" and backend == "auto":
            backend = "postgresql"

        if backend == "sqlite":
            return _make_sqlite(db_path or settings.SQLITE_FALLBACK_PATH, embedding_dim)

        if backend == "postgresql":
            if url:
                store, err = _try_pg_verbose(url)
            else:
                store, err = None, "DATABASE_URL not set"
            if store is not None:
                return store
            raise RuntimeError(
                f"PostgreSQL connection failed (url={url or '<unset>'}): {err}\n"
                "Cortex requires PostgreSQL in CLI mode.\n"
                "Run: bash setup.sh to configure PostgreSQL.\n"
                "If DATABASE_URL is set, verify it points to a reachable Postgres instance "
                "(host/port/credentials/database exists).\n"
                "Or set CORTEX_RUNTIME=cowork to allow SQLite fallback."
            )

        # "auto" in cowork mode: try PG, fall back to SQLite
        if url:
            store = _try_pg(url)
            if store is not None:
                return store

        return _make_sqlite(db_path or settings.SQLITE_FALLBACK_PATH, embedding_dim)


def _make_sqlite(path: str, embedding_dim: int):
    """Create SQLite fallback store."""
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

    logger.info("Using SQLite fallback at %s", path)
    return SqliteMemoryStore(db_path=path, embedding_dim=embedding_dim)
