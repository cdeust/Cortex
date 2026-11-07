"""Backend selection of ``memory_store._construct_store`` (issue #704, ADR-0535).

Every branch of the selection is pinned with PostgreSQL and SQLite replaced
by recorders: which store is returned, with which path and dimension, which
URL is tried, and the exact operator-facing error or warning text. These are
the behaviours the ADR-1122 mutation gate checks in the functions #704
changes (``_construct_store``, ``_resolve_backend_url``,
``_database_url_is_explicit``).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import mcp_server.infrastructure.memory_store as ms

_ENV = ("DATABASE_URL", "CORTEX_MEMORY_DATABASE_URL", "CORTEX_ALLOW_SQLITE_FALLBACK")
_FALLBACK_PATH = "/fallback/memory.db"
_PG_STORE = object()
_ERR = "OperationalError: refused"


@pytest.fixture
def world(monkeypatch):
    """Stubbed settings, PostgreSQL and SQLite; ``world.calls`` records both."""
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    state = SimpleNamespace(
        settings=SimpleNamespace(
            RUNTIME="cowork",
            STORE_BACKEND="auto",
            DATABASE_URL="",
            SQLITE_FALLBACK_PATH=_FALLBACK_PATH,
        ),
        pg_ok=True,
        calls=[],
        env=monkeypatch,
    )

    def try_pg(url):
        state.calls.append(("pg", url))
        return (_PG_STORE, None) if state.pg_ok else (None, _ERR)

    def make_sqlite(path, dim):
        state.calls.append(("sqlite", path, dim))
        return ("sqlite-store", path, dim)

    monkeypatch.setattr(ms, "get_memory_settings", lambda: state.settings)
    monkeypatch.setattr(ms, "_try_pg_verbose", try_pg)
    monkeypatch.setattr(ms, "_make_sqlite", make_sqlite)
    return state


def _configure(world, runtime, backend, settings_url=""):
    world.settings.RUNTIME = runtime
    world.settings.STORE_BACKEND = backend
    world.settings.DATABASE_URL = settings_url


def _warnings(caplog):
    return [
        (r.msg, r.args)
        for r in caplog.records
        if r.name == ms.__name__ and r.levelno == logging.WARNING
    ]


@pytest.mark.parametrize("runtime", ["cli", "cowork"])
def test_sqlite_backend_never_tries_postgresql(world, runtime):
    _configure(world, runtime, "sqlite", "postgresql://set/db")
    assert ms._construct_store("/given.db", 768) == ("sqlite-store", "/given.db", 768)
    assert world.calls == [("sqlite", "/given.db", 768)]


def test_defaults_use_the_fallback_path_and_384_dimensions(world):
    _configure(world, "cli", "sqlite")
    ms._construct_store()
    assert world.calls == [("sqlite", _FALLBACK_PATH, 384)]


@pytest.mark.parametrize("runtime", ["cli", "cowork"])
def test_auto_without_any_url_is_sqlite_without_a_connection(world, runtime):
    _configure(world, runtime, "auto")
    ms._construct_store("", 384)
    assert world.calls == [("sqlite", _FALLBACK_PATH, 384)]


def test_url_precedence_is_argument_then_environment_then_settings(world):
    _configure(world, "cli", "auto", "postgresql://settings/db")
    world.env.setenv("DATABASE_URL", "postgresql://env/db")
    assert ms._construct_store(database_url="postgresql://arg/db") is _PG_STORE
    assert ms._construct_store() is _PG_STORE
    world.env.delenv("DATABASE_URL")
    assert ms._construct_store() is _PG_STORE
    assert [c[1] for c in world.calls] == [
        "postgresql://arg/db",
        "postgresql://env/db",
        "postgresql://settings/db",
    ]


def test_postgresql_backend_without_url_names_the_fix(world):
    _configure(world, "cowork", "postgresql")
    with pytest.raises(RuntimeError) as info:
        ms._construct_store()
    assert str(info.value) == (
        "CORTEX_MEMORY_STORE_BACKEND=postgresql but no database URL is "
        "configured: set DATABASE_URL (or CORTEX_MEMORY_DATABASE_URL), "
        "or select the sqlite backend."
    )
    assert world.calls == []


_STRICT_FAILURE = (
    "PostgreSQL connection failed (url=postgresql://settings/db): " + _ERR + "\n"
    "Cortex requires PostgreSQL in CLI mode.\n"
    "Run: bash setup.sh to configure PostgreSQL.\n"
    "If DATABASE_URL is set, verify it points to a reachable Postgres instance "
    "(host/port/credentials/database exists).\n"
    "Or set CORTEX_RUNTIME=cowork (or CORTEX_ALLOW_SQLITE_FALLBACK=1) "
    "to allow SQLite fallback."
)


@pytest.mark.parametrize("backend", ["postgresql", "auto"])
@pytest.mark.parametrize("opt_in", [None, "0", "no"])
def test_strict_postgresql_failure_refuses_sqlite(world, backend, opt_in):
    """CLI auto with a URL is strict PostgreSQL, like the explicit backend."""
    _configure(world, "cli", backend, "postgresql://settings/db")
    if opt_in is not None:
        world.env.setenv("CORTEX_ALLOW_SQLITE_FALLBACK", opt_in)
    world.pg_ok = False
    with pytest.raises(RuntimeError) as info:
        ms._construct_store("/given.db", 384)
    assert str(info.value) == _STRICT_FAILURE
    assert world.calls == [("pg", "postgresql://settings/db")]


_SANDBOX_WARNING = (
    "PostgreSQL unavailable (%s); falling back to SQLite. "
    "This is expected for inspection/sandbox launches; "
    "production installs should set DATABASE_URL."
)


@pytest.mark.parametrize("opt_in", ["1", "true", "True", "yes"])
@pytest.mark.parametrize("db_path", ["", "/given.db"])
def test_strict_postgresql_failure_with_opt_in_falls_back(
    world, caplog, opt_in, db_path
):
    _configure(world, "cli", "postgresql", "postgresql://settings/db")
    world.env.setenv("CORTEX_ALLOW_SQLITE_FALLBACK", opt_in)
    world.pg_ok = False
    with caplog.at_level(logging.WARNING, logger=ms.__name__):
        ms._construct_store(db_path, 512)
    assert _warnings(caplog) == [(_SANDBOX_WARNING, (_ERR,))]
    assert world.calls == [
        ("pg", "postgresql://settings/db"),
        ("sqlite", db_path or _FALLBACK_PATH, 512),
    ]


def test_cowork_auto_with_a_reachable_url_uses_postgresql(world):
    _configure(world, "cowork", "auto", "postgresql://settings/db")
    assert ms._construct_store() is _PG_STORE
    assert world.calls == [("pg", "postgresql://settings/db")]


def test_cowork_auto_unreachable_default_url_falls_back(world, caplog):
    """A URL nobody named (settings only, no argument, no environment)."""
    _configure(world, "cowork", "auto", "postgresql://settings/db")
    world.pg_ok = False
    with caplog.at_level(logging.WARNING, logger=ms.__name__):
        ms._construct_store()
    assert _warnings(caplog) == [(_SANDBOX_WARNING, (_ERR,))]
    assert world.calls[-1] == ("sqlite", _FALLBACK_PATH, 384)


@pytest.mark.parametrize("opt_in", [None, "0"])
def test_cowork_auto_unreachable_explicit_url_refuses(world, opt_in):
    _configure(world, "cowork", "auto")
    if opt_in is not None:
        world.env.setenv("CORTEX_ALLOW_SQLITE_FALLBACK", opt_in)
    world.pg_ok = False
    with pytest.raises(RuntimeError) as info:
        ms._construct_store(database_url="postgresql://arg/db")
    assert str(info.value) == (
        "explicit DATABASE_URL unreachable (url=postgresql://arg/db): " + _ERR + "; "
        "refusing silent SQLite fallback; unset DATABASE_URL for "
        "sandbox mode or set CORTEX_ALLOW_SQLITE_FALLBACK=1 to opt in"
    )


@pytest.mark.parametrize("opt_in", ["1", "true", "TRUE", "yes"])
def test_cowork_auto_unreachable_explicit_url_with_opt_in(world, caplog, opt_in):
    _configure(world, "cowork", "auto")
    world.env.setenv("CORTEX_ALLOW_SQLITE_FALLBACK", opt_in)
    world.pg_ok = False
    with caplog.at_level(logging.WARNING, logger=ms.__name__):
        ms._construct_store("/given.db", 384, database_url="postgresql://arg/db")
    assert _warnings(caplog) == [
        (
            "Explicit DATABASE_URL (%s) unreachable (%s), but "
            "CORTEX_ALLOW_SQLITE_FALLBACK=1 opts in to SQLite fallback.",
            ("postgresql://arg/db", _ERR),
        )
    ]
    assert world.calls[-1] == ("sqlite", "/given.db", 384)


@pytest.mark.parametrize(
    ("runtime", "backend", "settings_url", "expected"),
    [
        ("cli", "auto", "postgresql://settings/db", "postgresql"),
        ("cli", "auto", "", "auto"),
        ("cowork", "auto", "postgresql://settings/db", "auto"),
        ("cli", "sqlite", "postgresql://settings/db", "sqlite"),
    ],
)
def test_cache_key_backend(world, runtime, backend, settings_url, expected):
    _configure(world, runtime, backend, settings_url)
    assert ms._resolve_backend_url("", 384, None) == (expected, settings_url)


def test_cache_key_url_precedence(world):
    _configure(world, "cowork", "auto", "postgresql://settings/db")
    world.env.setenv("DATABASE_URL", "postgresql://env/db")
    assert ms._resolve_backend_url("", 384, "postgresql://arg/db")[1] == (
        "postgresql://arg/db"
    )
    assert ms._resolve_backend_url("", 384, None)[1] == "postgresql://env/db"


@pytest.mark.parametrize(
    ("param", "env", "expected"),
    [
        (None, {}, False),
        ("", {}, True),
        (None, {"DATABASE_URL": ""}, True),
        (None, {"CORTEX_MEMORY_DATABASE_URL": "  "}, False),
        (None, {"CORTEX_MEMORY_DATABASE_URL": "postgresql://p/db"}, True),
    ],
)
def test_database_url_is_explicit(world, param, env, expected):
    for name, value in env.items():
        world.env.setenv(name, value)
    assert ms._database_url_is_explicit(param) is expected
