"""Memory store factory — runtime-aware backend selection.

source: ADR-0535"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

if TYPE_CHECKING:
    from mcp_server.infrastructure.pg_store import PgMemoryStore
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

    # source: ADR-0535
    MemoryStore = PgMemoryStore | SqliteMemoryStore

logger = logging.getLogger(__name__)

# source: ADR-0535
_shared_lock = threading.Lock()
_shared_stores: dict[tuple[str, str, int], "MemoryStore"] = {}


def _try_pg_verbose(
    database_url: str,
) -> tuple[PgMemoryStore | None, str | None]:
    """Try connecting to PostgreSQL. Returns (store, error_message)."""
    try:
        import psycopg  # noqa: PLC0415, F401 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

        from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it

        return PgMemoryStore(database_url=database_url), None
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        msg = f"{type(exc).__name__}: {exc}"
        logger.warning("PostgreSQL unavailable (%s), falling back to SQLite", msg)
        return None, msg


if not TYPE_CHECKING:

    class MemoryStore:
        """Runtime-aware store factory.

                This class is only the *runtime* callable. For the type checker the
                `MemoryStore` name is bound (in the TYPE_CHECKING block at the top of
                this module) to `PgMemoryStore | SqliteMemoryStore`, the actual union
                of backends `__new__` returns — so annotations see the store interface.

        source: ADR-0535"""

        def __new__(
            cls,
            db_path: str = "",
            embedding_dim: int = 384,
            *,
            database_url: str | None = None,
        ):
            return _construct_store(db_path, embedding_dim, database_url=database_url)


def get_shared_store(
    db_path: str = "",
    embedding_dim: int = 384,
    *,
    database_url: str | None = None,
) -> "MemoryStore":
    """Return a process-wide cached store, one per (backend, url, dim) key.

    source: ADR-0535"""
    key = _resolve_key(db_path, embedding_dim, database_url)
    with _shared_lock:
        store = _shared_stores.get(key)
        if store is None:
            store = _construct_store(db_path, embedding_dim, database_url=database_url)
            _shared_stores[key] = store
        return store


def reset_shared_store() -> None:
    """Close and evict all cached shared stores (test teardown / shutdown).

    Releases every store's psycopg pools so connections do not leak across
    test modules. Subsequent get_shared_store() calls reconstruct lazily.
    """
    with _shared_lock:
        for store in _shared_stores.values():
            close = getattr(store, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 — pragma: no cover - defensive teardown
                    logger.warning("error closing shared store", exc_info=True)
        _shared_stores.clear()


def _resolve_backend_url(
    db_path: str, embedding_dim: int, database_url: str | None
) -> tuple[str, str]:
    """Resolve the backend and URL used as store cache-key discriminators.

    source: ADR-0535"""

    settings = get_memory_settings()
    backend = settings.STORE_BACKEND
    url = database_url or os.environ.get("DATABASE_URL", "") or settings.DATABASE_URL
    if settings.RUNTIME == "cli" and backend == "auto":
        backend = "postgresql"
    return backend, url


def _resolve_key(
    db_path: str, embedding_dim: int, database_url: str | None
) -> tuple[str, str, int]:
    backend, url = _resolve_backend_url(db_path, embedding_dim, database_url)
    return (backend, url, embedding_dim)


def _construct_store(
    db_path: str = "",
    embedding_dim: int = 384,
    *,
    database_url: str | None = None,
) -> "MemoryStore":
    """Build a fresh store using runtime-aware backend selection.

    source: ADR-0535"""

    settings = get_memory_settings()
    runtime = settings.RUNTIME
    backend = settings.STORE_BACKEND
    url = database_url or os.environ.get("DATABASE_URL", "") or settings.DATABASE_URL

    # source: ADR-0535
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
        # source: ADR-0535
        allow_fallback = not url or os.environ.get(
            "CORTEX_ALLOW_SQLITE_FALLBACK", ""
        ).lower() in ("1", "true", "yes")
        if allow_fallback:
            logger.warning(
                "PostgreSQL unavailable (%s); falling back to SQLite. "
                "This is expected for inspection/sandbox launches; "
                "production installs should set DATABASE_URL.",
                err,
            )
            return _make_sqlite(db_path or settings.SQLITE_FALLBACK_PATH, embedding_dim)
        raise RuntimeError(
            f"PostgreSQL connection failed (url={url or '<unset>'}): {err}\n"
            "Cortex requires PostgreSQL in CLI mode.\n"
            "Run: bash setup.sh to configure PostgreSQL.\n"
            "If DATABASE_URL is set, verify it points to a reachable Postgres instance "
            "(host/port/credentials/database exists).\n"
            "Or set CORTEX_RUNTIME=cowork (or CORTEX_ALLOW_SQLITE_FALLBACK=1) "
            "to allow SQLite fallback."
        )

    # source: ADR-0535
    if url:
        store, err = _try_pg_verbose(url)
        if store is not None:
            return store
        if _database_url_is_explicit(database_url):
            allow_fallback = os.environ.get(
                "CORTEX_ALLOW_SQLITE_FALLBACK", ""
            ).lower() in ("1", "true", "yes")
            if not allow_fallback:
                raise RuntimeError(
                    f"explicit DATABASE_URL unreachable (url={url}): {err}; "
                    "refusing silent SQLite fallback; unset DATABASE_URL for "
                    "sandbox mode or set CORTEX_ALLOW_SQLITE_FALLBACK=1 to opt in"
                )
            logger.warning(
                "Explicit DATABASE_URL (%s) unreachable (%s), but "
                "CORTEX_ALLOW_SQLITE_FALLBACK=1 opts in to SQLite fallback.",
                url,
                err,
            )
        else:
            logger.warning(
                "PostgreSQL unavailable (%s); falling back to SQLite. "
                "This is expected for inspection/sandbox launches; "
                "production installs should set DATABASE_URL.",
                err,
            )

    return _make_sqlite(db_path or settings.SQLITE_FALLBACK_PATH, embedding_dim)


def _database_url_is_explicit(database_url_param: str | None) -> bool:
    """True when the resolved URL came from an operator, not the DB-less
        inspection default.

    source: ADR-0535"""
    return database_url_param is not None or "DATABASE_URL" in os.environ


def _make_sqlite(path: str, embedding_dim: int) -> "SqliteMemoryStore":
    """Create SQLite fallback store."""

    logger.info("Using SQLite fallback at %s", path)
    return SqliteMemoryStore(db_path=path, embedding_dim=embedding_dim)
