"""scripts/launcher_backend.py: the first launch keeps an earlier local PostgreSQL.

Before ADR-1104 a marketplace install had no marker and ran on
``postgresql://localhost:5432/cortex`` through libpq. Reviews of #749 showed
that any protocol probe is narrower than libpq, so SQLite is chosen only when
that URL certainly failed: the port refuses and no PG* variable configures
libpq. These tests use free local ports and never dial the real 5432.

source: ADR-1104
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import launcher_backend  # noqa: E402

_MARKER = "backend.json"


@pytest.fixture
def no_libpq_settings(monkeypatch):
    for name in [n for n in os.environ if n.startswith("PG")]:
        monkeypatch.delenv(name)


def _earlier_state(tmp_path: Path) -> Path:
    methodology = tmp_path / "methodology"
    methodology.mkdir()
    (methodology / "session-log.json").write_text("{}")
    return methodology


def _point_at(monkeypatch, port: int) -> None:
    monkeypatch.setattr(launcher_backend, "LEGACY_HOST", "127.0.0.1")
    monkeypatch.setattr(launcher_backend, "LEGACY_PORT", port)


def _closed_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as unused:
        return unused.getsockname()[1]


def test_a_fresh_install_is_sqlite_without_dialing(tmp_path, monkeypatch):
    def dial(_environ):
        raise AssertionError("a fresh install must not dial PostgreSQL")

    monkeypatch.setattr(launcher_backend, "legacy_store_answer", dial)
    methodology = tmp_path / "methodology"
    methodology.mkdir()
    (methodology / "backend.json.tmp1").write_text("")
    (methodology / ".DS_Store").write_text("")
    assert launcher_backend.decide(methodology, _MARKER) == ("sqlite", "fresh install")
    assert launcher_backend.decide(tmp_path / "absent", _MARKER)[0] == "sqlite"


def test_a_listening_server_keeps_postgresql(tmp_path, monkeypatch, no_libpq_settings):
    with socket.create_server(("127.0.0.1", 0)) as listener:
        _point_at(monkeypatch, listener.getsockname()[1])
        backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql", why
    assert "libpq decides" in why


def test_a_refused_port_is_sqlite_with_the_reason(
    tmp_path, monkeypatch, no_libpq_settings
):
    _point_at(monkeypatch, _closed_port())
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite"
    assert "nothing listens there" in why and "set database_url" in why


@pytest.mark.parametrize("name", ["PGSERVICE", "PGHOSTADDR", "PGGSSENCMODE"])
def test_libpq_settings_keep_postgresql_even_when_refused(
    tmp_path, monkeypatch, no_libpq_settings, name
):
    monkeypatch.setenv(name, "x")
    _point_at(monkeypatch, _closed_port())
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql" and name in why


def test_an_unclear_connect_error_keeps_postgresql(
    tmp_path, monkeypatch, no_libpq_settings
):
    def times_out(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(launcher_backend.socket, "create_connection", times_out)
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql" and "no clear answer" in why


def test_the_decision_is_recorded_and_printed(tmp_path, monkeypatch, capsys):
    from mcp_server.infrastructure import backend_marker

    marker = tmp_path / "methodology" / "backend.json"
    monkeypatch.setattr(backend_marker, "BACKEND_MARKER_PATH", marker)
    launcher_backend.persist_first_decision()
    assert backend_marker.read_backend_marker(marker)["backend"] == "sqlite"
    assert "storage: sqlite (fresh install)" in capsys.readouterr().err
    assert [p.name for p in marker.parent.iterdir()] == ["backend.json"]
