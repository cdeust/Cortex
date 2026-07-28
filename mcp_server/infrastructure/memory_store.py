"""Memory store factory — runtime-aware backend selection.

CLI mode: PostgreSQL required, no silent fallback.
Cowork mode: tries PostgreSQL, falls back to SQLite when no DATABASE_URL was
explicitly configured (the DB-less inspection/sandbox contract). When
DATABASE_URL IS explicitly set (env var or constructor arg) and unreachable,
falls back only with CORTEX_ALLOW_SQLITE_FALLBACK=1 opt-in — otherwise raises,
so a misconfigured production DATABASE_URL never silently redirects writes to
a different database. See _database_url_is_explicit for the explicitness test.
"""

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

    # `MemoryStore` is a *factory*: its __new__ (below) returns a fully-built
    # PgMemoryStore or SqliteMemoryStore, never a bare `MemoryStore` instance.
    # For the type checker the public name therefore resolves to the union of
    # the concrete backends the factory can produce, so every
    # `store: MemoryStore` annotation and every `MemoryStore(...)` /
    # `get_shared_store()` result exposes the real store interface instead of
    # an empty factory shell. At runtime the name is the class defined in the
    # `else` branch below (a callable that dispatches to _construct_store).
    MemoryStore = PgMemoryStore | SqliteMemoryStore

logger = logging.getLogger(__name__)

# Process-wide store cache. 37 MCP handlers each used to construct their own
# store via MemoryStore(...), and each store eagerly opens psycopg pools
# (min2/max8 interactive + min1/max2 batch). conftest only reset 5 of them, so
# connections leaked past 60 and the 1800s batch-pool acquire timeout produced
# the 30-minute CI hangs. Caching one store per (backend, url, dim) caps live
# connections at a single store's two pools regardless of handler count, and
# fixes the same connection-quota leak in production.
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

        CLI mode: PostgreSQL required (auto → postgresql). Raises on failure.
        Cowork mode: tries PostgreSQL, falls back to SQLite.
        Explicit sqlite backend always works (for testing).

        This class is only the *runtime* callable. For the type checker the
        `MemoryStore` name is bound (in the TYPE_CHECKING block at the top of
        this module) to `PgMemoryStore | SqliteMemoryStore`, the actual union
        of backends `__new__` returns — so annotations see the store interface.
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
) -> "MemoryStore":
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
                except Exception:  # noqa: BLE001 — pragma: no cover - defensive teardown
                    logger.warning("error closing shared store", exc_info=True)
        _shared_stores.clear()


def _resolve_backend_url(
    db_path: str, embedding_dim: int, database_url: str | None
) -> tuple[str, str]:
    """Resolve the (backend, url) a construction would target — the cache key
    discriminators. Mirrors the branch selection in _construct_store."""

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

    CLI mode: PostgreSQL required (auto → postgresql). Raises on failure.
    Cowork mode: tries PostgreSQL, falls back to SQLite.
    Explicit sqlite backend always works (for testing).
    """

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

    # "auto" in cowork mode: try PG, fall back to SQLite — but only when the
    # URL came from the DB-less inspection default, not from an operator who
    # explicitly configured a target. An explicit DATABASE_URL that fails to
    # connect must not silently redirect writes to a different database
    # (integrity risk: the caller believes it is writing to Postgres).
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

    ``settings.DATABASE_URL`` (memory_config.py) carries a hardcoded default
    (``postgresql://127.0.0.1:5432/cortex``) so it is indistinguishable in
    *value* from a real operator-supplied URL that happens to match it —
    the explicitness test must be on the SOURCE (was a URL supplied at all),
    not the value. Two sources count as explicit, matching the priority
    order in ``_construct_store``/``_resolve_backend_url``:
      1. ``database_url`` passed directly to the constructor (CLI arg, test
         fixture, or caller-supplied override).
      2. The bare ``DATABASE_URL`` env var — the convention this codebase
         uses everywhere else (pg_store.py, doctor.py, session_start.py,
         etc.) to mean "the operator configured Postgres".
    ``CORTEX_MEMORY_DATABASE_URL`` (the pydantic-settings prefixed var
    documented in README.md for the "postgresql"/"auto" backend) is NOT
    checked here: pydantic-settings folds it into ``settings.DATABASE_URL``
    before this function ever sees it, so by the time execution reaches
    here it is already indistinguishable from the hardcoded default. This
    is a known blind spot — an operator using only the prefixed var will
    get the sandbox (silent-fallback-with-warning) behavior instead of the
    strict one. Documented rather than silently "fixed" by inspecting
    pydantic internals, because doing so would require importing the
    settings' env-value provenance, which pydantic-settings does not
    expose. source: this file, _resolve_backend_url and _construct_store
    priority chain (database_url param > os.environ["DATABASE_URL"] >
    settings.DATABASE_URL).
    """
    return database_url_param is not None or "DATABASE_URL" in os.environ


def _make_sqlite(path: str, embedding_dim: int) -> "SqliteMemoryStore":
    """Create SQLite fallback store."""

    logger.info("Using SQLite fallback at %s", path)
    return SqliteMemoryStore(db_path=path, embedding_dim=embedding_dim)
