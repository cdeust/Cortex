"""backend_resolution: the first launch keeps an earlier local PostgreSQL.

Before ADR-1104 a marketplace install had no marker and ran on
``postgresql://localhost:5432/cortex`` through libpq. Reviews of #749 showed
that any protocol probe is narrower than libpq, so SQLite is chosen only when
that URL certainly failed: the port refuses and no PG* variable configures
libpq. These tests use free local ports and never dial the real 5432.

source: ADR-1104
source: ADR-1110
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from mcp_server.infrastructure import backend_resolution

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
    monkeypatch.setattr(backend_resolution, "LEGACY_HOST", "127.0.0.1")
    monkeypatch.setattr(backend_resolution, "LEGACY_PORT", port)


def _closed_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as unused:
        return unused.getsockname()[1]


def test_a_fresh_install_is_sqlite_without_dialing(tmp_path, monkeypatch):
    def dial(_environ):
        raise AssertionError("a fresh install must not dial PostgreSQL")

    monkeypatch.setattr(backend_resolution, "legacy_store_answer", dial)
    methodology = tmp_path / "methodology"
    methodology.mkdir()
    (methodology / "backend.json.tmp1").write_text("")
    (methodology / ".DS_Store").write_text("")
    assert backend_resolution.decide(methodology, _MARKER) == (
        "sqlite",
        "fresh install",
    )
    assert backend_resolution.decide(tmp_path / "absent", _MARKER)[0] == "sqlite"


def test_a_listening_server_keeps_postgresql(tmp_path, monkeypatch, no_libpq_settings):
    with socket.create_server(("127.0.0.1", 0)) as listener:
        _point_at(monkeypatch, listener.getsockname()[1])
        backend, why = backend_resolution.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql", why
    assert "libpq decides" in why


def test_a_refused_port_is_sqlite_with_the_reason(
    tmp_path, monkeypatch, no_libpq_settings
):
    _point_at(monkeypatch, _closed_port())
    backend, why = backend_resolution.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite"
    assert "nothing listens there" in why and "set database_url" in why


@pytest.mark.parametrize("name", ["PGSERVICE", "PGHOSTADDR", "PGGSSENCMODE"])
def test_libpq_settings_keep_postgresql_even_when_refused(
    tmp_path, monkeypatch, no_libpq_settings, name
):
    monkeypatch.setenv(name, "x")
    _point_at(monkeypatch, _closed_port())
    backend, why = backend_resolution.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql" and name in why


def _addresses(monkeypatch, *ports: int) -> None:
    """``localhost`` resolving to one 127.0.0.1 address per port."""
    found = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))
        for port in ports
    ]
    monkeypatch.setattr(backend_resolution.socket, "getaddrinfo", lambda *a, **k: found)


def test_an_unclear_connect_error_keeps_postgresql(
    tmp_path, monkeypatch, no_libpq_settings
):
    def times_out(self, _address):
        raise TimeoutError("timed out")

    _addresses(monkeypatch, _closed_port())
    monkeypatch.setattr(backend_resolution.socket.socket, "connect", times_out)
    backend, why = backend_resolution.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql" and "no clear answer" in why


def test_one_listening_address_among_refusals_keeps_postgresql(
    tmp_path, monkeypatch, no_libpq_settings
):
    """A refusal reported last must not hide a listener on another address."""
    with socket.create_server(("127.0.0.1", 0)) as listener:
        _addresses(monkeypatch, _closed_port(), listener.getsockname()[1])
        backend, why = backend_resolution.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql", why


def test_a_timeout_before_a_refusal_keeps_postgresql(
    tmp_path, monkeypatch, no_libpq_settings
):
    """Review of 0839d874 (B1): create_connection raised only the last
    address's error, so ::1 timing out then 127.0.0.1 refusing chose SQLite."""
    closed = _closed_port()
    found = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.2", closed)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", closed)),
    ]
    monkeypatch.setattr(backend_resolution.socket, "getaddrinfo", lambda *a, **k: found)
    real = socket.socket.connect

    def connect(self, address):
        if address[0] == "127.0.0.2":
            raise socket.timeout("timed out")
        return real(self, address)

    monkeypatch.setattr(backend_resolution.socket.socket, "connect", connect)
    backend, why = backend_resolution.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql", why


def test_every_address_refusing_is_sqlite(tmp_path, monkeypatch, no_libpq_settings):
    _addresses(monkeypatch, _closed_port(), _closed_port())
    backend, why = backend_resolution.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite" and "every address refuses" in why


def test_no_address_is_sqlite(tmp_path, monkeypatch, no_libpq_settings):
    def unresolved(*_args, **_kwargs):
        raise socket.gaierror(8, "nodename nor servname provided")

    monkeypatch.setattr(backend_resolution.socket, "getaddrinfo", unresolved)
    backend, why = backend_resolution.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite" and "has no address" in why


def test_the_decision_is_recorded_and_printed(tmp_path, monkeypatch, capsys):
    from mcp_server.infrastructure import backend_marker

    marker = tmp_path / "methodology" / "backend.json"
    monkeypatch.setattr(backend_marker, "BACKEND_MARKER_PATH", marker)
    backend_resolution.persist_first_decision()
    assert backend_marker.read_backend_marker(marker)["backend"] == "sqlite"
    assert "storage: sqlite (fresh install)" in capsys.readouterr().err
    assert [p.name for p in marker.parent.iterdir()] == ["backend.json"]
