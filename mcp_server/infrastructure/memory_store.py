"""Memory store factory — PostgreSQL with SQLite fallback.

Tries PostgreSQL first (via DATABASE_URL). Falls back to SQLite
when PostgreSQL is unavailable (e.g., sandboxed environments).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _try_pg(database_url: str):
    """Try connecting to PostgreSQL. Returns PgMemoryStore or None."""
    try:
        import psycopg  # noqa: F401
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        return PgMemoryStore(database_url=database_url)
    except Exception as exc:
        logger.warning("PostgreSQL unavailable (%s), falling back to SQLite", exc)
        return None


class MemoryStore:
    """Factory that tries PostgreSQL first, falls back to SQLite.

    Returns the appropriate store instance via __new__ — callers
    get a PgMemoryStore or SqliteMemoryStore transparently.
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
        backend = settings.STORE_BACKEND
        url = (
            database_url or os.environ.get("DATABASE_URL", "") or settings.DATABASE_URL
        )

        # Explicit backend selection
        if backend == "sqlite":
            return _make_sqlite(db_path or settings.SQLITE_FALLBACK_PATH, embedding_dim)

        if backend == "postgresql":
            store = _try_pg(url) if url else None
            if store is not None:
                return store
            raise RuntimeError(
                "STORE_BACKEND=postgresql but PostgreSQL connection failed"
            )

        # Auto mode: try PG first, fall back to SQLite
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
