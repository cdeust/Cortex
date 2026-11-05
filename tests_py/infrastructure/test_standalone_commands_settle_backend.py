"""PR #865 review B1: standalone commands read the backend marker first.

``python -m mcp_server.portability`` and ``python -m mcp_server.migrate``
build a store outside the server and the hooks. With no default URL in code
(issue #704), a PostgreSQL marker and no URL in the shell must still reach
the marker's PostgreSQL, as ``mcp_server/__main__.py`` does, never an empty
SQLite store chosen silently.
"""

from __future__ import annotations

import os

import pytest

from mcp_server.infrastructure import backend_marker
from mcp_server.infrastructure.memory_config import get_memory_settings

_KEYS = ("DATABASE_URL", "CORTEX_MEMORY_DATABASE_URL", "CORTEX_MEMORY_STORE_BACKEND")


@pytest.fixture
def postgresql_marker(tmp_path, monkeypatch):
    """A PostgreSQL marker, no URL and no backend in the environment."""
    saved = dict(os.environ)
    for key in _KEYS:
        os.environ.pop(key, None)
    marker = tmp_path / "backend.json"
    backend_marker.write_backend_marker("postgresql", "test", marker)
    monkeypatch.setattr(backend_marker, "BACKEND_MARKER_PATH", marker)
    get_memory_settings.cache_clear()
    yield marker
    os.environ.clear()
    os.environ.update(saved)
    get_memory_settings.cache_clear()


def _seen_backend() -> tuple[str, str]:
    return (
        os.environ.get("CORTEX_MEMORY_STORE_BACKEND", ""),
        os.environ.get("DATABASE_URL", ""),
    )


def test_portability_settles_the_marker_before_building_its_store(
    postgresql_marker, monkeypatch
):
    from mcp_server import portability

    seen = []

    class StopError(Exception):
        """Raised where the store would be built, before any connection."""

    def store():
        seen.append(_seen_backend())
        raise StopError

    monkeypatch.setattr(portability, "_store", store)
    with pytest.raises(StopError):
        portability.main(["export", "/tmp/project", "/tmp/out.jsonl"])
    assert seen == [("postgresql", "postgresql://localhost:5432/cortex")]


def test_migrate_settles_the_marker_before_resolving_its_url(
    postgresql_marker, monkeypatch
):
    pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")
    from mcp_server import migrate

    seen = []

    def probe(url, target_hash):
        seen.append(url)
        raise OSError("stop before any connection")

    monkeypatch.setattr(migrate, "_probe_was_current", probe)
    assert migrate._run() == 1
    assert seen == ["postgresql://localhost:5432/cortex"]


def test_an_invalid_marker_ends_the_command_in_one_line(
    postgresql_marker, monkeypatch, capsys
):
    from mcp_server import portability

    postgresql_marker.write_text("not json")
    monkeypatch.setattr(portability, "_store", lambda: pytest.fail("a store was built"))
    assert portability.main(["export", "/tmp/project", "/tmp/out.jsonl"]) == 1
    assert "cortex portability: Cortex not ready" in capsys.readouterr().err


_MAINTENANCE_SCRIPTS = (
    "backfill_wiki_titles_2026_07_14",
    "backfill_write_class",
    "memory_dedup_exact",
    "memory_domain_backfill",
    "memory_reheat",
    "memory_staleness_revalidate",
    "near_dup_calibrate",
    "provenance_sweep",
    "wiki_citation_seed",
)


@pytest.mark.parametrize("name", _MAINTENANCE_SCRIPTS)
def test_maintenance_scripts_settle_before_their_store(name):
    """Codex review on 749bf05: the scripts under scripts/ that build the
    shared store read the marker first (structural: the settle call precedes
    the store construction in the same function)."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    ).read_text()
    settle = source.index(f'settle_for_command("{name}")')
    build = source.index("get_shared_store(settings.DB_PATH")
    assert settle < build


def test_memory_staleness_revalidate_reaches_the_marker_postgresql(
    postgresql_marker, monkeypatch
):
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "memory_staleness_revalidate.py"
    )
    spec = importlib.util.spec_from_file_location("_staleness_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = []

    class StopError(Exception):
        """Raised where the store would be built, before any connection."""

    def store(*args):
        seen.append(_seen_backend())
        raise StopError

    monkeypatch.setattr(module, "get_shared_store", store)
    with pytest.raises(StopError):
        module.main([])
    assert seen == [("postgresql", "postgresql://localhost:5432/cortex")]


# ── settle_for_command itself (mutation gate, ADR-1122) ────────────────────


def test_settle_for_command_settles_the_process_environment(monkeypatch):
    from mcp_server.infrastructure import backend_resolution

    seen = []
    monkeypatch.setattr(backend_resolution, "settle_backend", seen.append)
    assert backend_resolution.settle_for_command("prog") is True
    assert seen == [os.environ]


@pytest.mark.parametrize(
    "error",
    [
        backend_marker.BackendMarkerError("bad marker"),
        pytest.param("managed", id="ManagedPgError"),
        OSError("disk gone"),
    ],
)
def test_settle_for_command_reports_a_backend_it_cannot_settle(
    monkeypatch, capsys, error
):
    from mcp_server.infrastructure import backend_resolution, managed_pg

    if error == "managed":
        error = managed_pg.ManagedPgError("server down")

    def fail(environ):
        raise error

    monkeypatch.setattr(backend_resolution, "settle_backend", fail)
    assert backend_resolution.settle_for_command("prog") is False
    captured = capsys.readouterr()
    assert captured.err == f"prog: Cortex not ready: {error}\n"
    assert captured.out == ""


# ── portability.main end to end, store and handlers faked ──────────────────


@pytest.fixture
def portability_cli(monkeypatch):
    from mcp_server import portability
    from mcp_server.handlers import memory_portability
    from mcp_server.infrastructure import backend_resolution

    calls = []
    store = object()

    def settle(prog):
        calls.append(("settle", prog))
        return True

    def export(*args, **kwargs):
        calls.append(("export", args, kwargs))
        return {"exported": 1}

    def restore(*args, **kwargs):
        calls.append(("import", args, kwargs))
        return {"imported": 2}

    monkeypatch.setattr(backend_resolution, "settle_for_command", settle)
    monkeypatch.setattr(portability, "_store", lambda: store)
    monkeypatch.setattr(memory_portability, "export_project", export)
    monkeypatch.setattr(memory_portability, "import_export", restore)
    return portability, store, calls


@pytest.mark.parametrize("flag", [True, False])
def test_portability_export_passes_its_arguments(portability_cli, capsys, flag):
    portability, store, calls = portability_cli
    argv = ["export", "/proj", "/out.jsonl", *(["--include-global"] if flag else [])]
    assert portability.main(argv) == 0
    assert calls == [
        ("settle", "cortex portability"),
        ("export", (store, "/proj", "/out.jsonl"), {"include_global": flag}),
    ]
    assert capsys.readouterr().out == '{"exported": 1}\n'


@pytest.mark.parametrize("trust", [True, False])
def test_portability_import_passes_its_arguments(portability_cli, capsys, trust):
    portability, store, calls = portability_cli
    argv = ["import", "/in.jsonl", "--into", "/root", *(["--trust-flags"] * trust)]
    assert portability.main(argv) == 0
    assert calls[1:] == [
        (
            "import",
            (store, "/in.jsonl"),
            {"into_project_root": "/root", "trust_flags": trust},
        )
    ]
    assert capsys.readouterr().out == '{"imported": 2}\n'


@pytest.mark.parametrize("error", [ValueError("not an export"), OSError("gone")])
def test_portability_reports_a_bad_file_on_stderr(
    portability_cli, monkeypatch, capsys, error
):
    from mcp_server.handlers import memory_portability

    portability, _, _ = portability_cli

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(memory_portability, "import_export", fail)
    assert portability.main(["import", "/in.jsonl"]) == 1
    captured = capsys.readouterr()
    assert captured.err == f"cortex portability: {error}\n"
    assert captured.out == ""


# ── migrate._run around the settle step ────────────────────────────────────


def test_migrate_reports_an_invalid_marker_on_its_exit_contract(
    postgresql_marker, capsys
):
    pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")
    from mcp_server import migrate

    postgresql_marker.write_text("not json")
    assert migrate._run() == 1
    assert capsys.readouterr().err.startswith("cortex-migrate: Cortex not ready: ")


def test_migrate_builds_its_store_on_the_resolved_url(monkeypatch, capsys):
    pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")
    from mcp_server import migrate
    from mcp_server.infrastructure import backend_resolution, pg_store

    built = []

    class FakeStore:
        def __init__(self, database_url=None):
            built.append(database_url)

        def close(self):
            built.append("closed")

    monkeypatch.setattr(backend_resolution, "settle_for_command", lambda prog: True)
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.invalid/named")
    monkeypatch.setattr(migrate, "_probe_was_current", lambda url, target: True)
    monkeypatch.setattr(pg_store, "PgMemoryStore", FakeStore)
    assert migrate._run() == 0
    assert built == ["postgresql://db.invalid/named", "closed"]
    assert capsys.readouterr().out == "cortex-migrate: schema up to date\n"
