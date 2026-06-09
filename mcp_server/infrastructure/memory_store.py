"""Memory store factory — runtime-aware backend selection.

CLI mode: PostgreSQL required, no silent fallback.
Cowork mode: tries PostgreSQL, falls back to SQLite.
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

# Process-wide store cache. 37 MCP handlers each used to construct their own
# store via MemoryStore(...), and each store eagerly opens psycopg pools
# (min2/max8 interactive + min1/max2 batch). conftest only reset 5 of them, so
# connections leaked past 60 and the 1800s batch-pool acquire timeout produced
# the 30-minute CI hangs. Caching one store per (backend, url, dim) caps live
# connections at a single store's two pools regardless of handler count, and
# fixes the same connection-quota leak in production.
_shared_lock = threading.Lock()
_shared_stores: dict[tuple[str, str, int], object] = {}


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
        return _construct_store(db_path, embedding_dim, database_url=database_url)


def get_shared_store(
    db_path: str = "",
    embedding_dim: int = 384,
    *,
    database_url: str | None = None,
):
    """Return a process-wide cached store, one per (backend, url, dim) key.

    Handlers MUST use this instead of constructing MemoryStore(...) directly:
    each store owns two psycopg pools, so one cached store caps live
    connections regardless of how many of the 37 handlers ask for it. See the
    module-level note on _shared_stores for the CI-hang / quota-leak history.
    """
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
                except Exception:  # pragma: no cover - defensive teardown
                    logger.warning("error closing shared store", exc_info=True)
        _shared_stores.clear()


def _resolve_backend_url(
    db_path: str, embedding_dim: int, database_url: str | None
) -> tuple[str, str]:
    """Resolve the (backend, url) a construction would target — the cache key
    discriminators. Mirrors the branch selection in _construct_store."""
    from mcp_server.infrastructure.memory_config import get_memory_settings

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
):
    """Build a fresh store using runtime-aware backend selection.

    CLI mode: PostgreSQL required (auto → postgresql). Raises on failure.
    Cowork mode: tries PostgreSQL, falls back to SQLite.
    Explicit sqlite backend always works (for testing).
    """
    from mcp_server.infrastructure.memory_config import get_memory_settings

    settings = get_memory_settings()
    runtime = settings.RUNTIME
    backend = settings.STORE_BACKEND
    url = database_url or os.environ.get("DATABASE_URL", "") or settings.DATABASE_URL

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
        # Inspection-mode fallback — Glama's sandbox, CI smoke
        # tests, and first-glance experimenters launch Cortex with
        # no DATABASE_URL. Rather than hard-fail and leave them
        # unable to even see the tool surface, drop to SQLite with
        # a loud warning. Real production users who have
        # configured Postgres will see the PG connect succeed;
        # only unset/unreachable installs trip this path.
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
