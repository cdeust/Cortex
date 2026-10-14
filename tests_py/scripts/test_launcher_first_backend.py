"""scripts/launcher_backend.py: the first launch keeps an earlier local PostgreSQL.

Before ADR-1104 a marketplace install had no marker and ran on
``postgresql://localhost:5432/cortex``. The review of #749 found that such a
user would have been moved to an empty SQLite store. The decision now follows
``install-plugin.sh`` (ADR-0740), against a fake server on a free port: these
tests never dial the real 5432.

source: ADR-1104
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import launcher_backend  # noqa: E402

_MARKER = "backend.json"


def _message(kind: bytes, payload: bytes) -> bytes:
    return kind + struct.pack("!i", len(payload) + 4) + payload


_READY = (
    _message(b"R", struct.pack("!i", 0))
    + _message(b"S", b"a\x00b\x00")
    + _message(b"Z", b"I")
)
_NO_DATABASE = _message(b"R", struct.pack("!i", 0)) + _message(
    b"E", b'SFATAL\x00C3D000\x00Mdatabase "cortex" does not exist\x00\x00'
)
_PASSWORD = _message(b"R", struct.pack("!i", 10) + b"SCRAM-SHA-256\x00\x00")


@pytest.fixture
def fake_server(monkeypatch):
    """Serve one canned reply on a free port; record the startup packet."""
    servers = []

    def start(reply: bytes) -> dict:
        listener = socket.create_server(("127.0.0.1", 0))
        seen: dict = {}

        def serve():
            conn, _ = listener.accept()
            with conn:
                length = struct.unpack("!i", conn.recv(4))[0]
                seen["startup"] = conn.recv(length - 4)
                conn.sendall(reply)
                seen["after"] = conn.recv(5)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        servers.append((listener, thread))
        monkeypatch.setattr(launcher_backend, "LEGACY_HOST", "127.0.0.1")
        monkeypatch.setattr(launcher_backend, "LEGACY_PORT", listener.getsockname()[1])
        return seen

    yield start
    for listener, thread in servers:
        thread.join(timeout=5)
        listener.close()


def _earlier_state(tmp_path: Path) -> Path:
    methodology = tmp_path / "methodology"
    methodology.mkdir()
    (methodology / "session-log.json").write_text("{}")
    return methodology


def test_a_fresh_install_is_sqlite_without_dialing(tmp_path, monkeypatch):
    def dial(_user):
        raise AssertionError("a fresh install must not dial PostgreSQL")

    monkeypatch.setattr(launcher_backend, "local_database_answer", dial)
    (tmp_path / "methodology").mkdir()
    (tmp_path / "methodology" / "backend.json.tmp1").write_text("")
    assert launcher_backend.decide(tmp_path / "methodology", _MARKER) == (
        "sqlite",
        "fresh install",
    )
    assert launcher_backend.decide(tmp_path / "absent", _MARKER)[0] == "sqlite"


def test_an_earlier_local_cortex_database_keeps_postgresql(tmp_path, fake_server):
    seen = fake_server(_READY)
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql", why
    assert b"database\x00cortex\x00" in seen["startup"]


@pytest.mark.parametrize(
    ("reply", "reason"),
    [(_NO_DATABASE, 'database "cortex" does not exist'), (_PASSWORD, "password")],
)
def test_a_database_that_does_not_open_is_sqlite_with_the_reason(
    tmp_path, fake_server, reply, reason
):
    fake_server(reply)
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite"
    assert reason in why and "set database_url" in why


def test_nothing_listening_is_sqlite_with_the_reason(tmp_path, monkeypatch):
    with socket.create_server(("127.0.0.1", 0)) as unused:
        port = unused.getsockname()[1]
    monkeypatch.setattr(launcher_backend, "LEGACY_HOST", "127.0.0.1")
    monkeypatch.setattr(launcher_backend, "LEGACY_PORT", port)
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite"
    assert "no database answered" in why


def test_the_decision_is_recorded_and_printed(tmp_path, monkeypatch, capsys):
    from mcp_server.infrastructure import backend_marker

    marker = tmp_path / "methodology" / "backend.json"
    monkeypatch.setattr(backend_marker, "BACKEND_MARKER_PATH", marker)
    launcher_backend.persist_first_decision()
    assert backend_marker.read_backend_marker(marker)["backend"] == "sqlite"
    assert "storage: sqlite (fresh install)" in capsys.readouterr().err
    assert [p.name for p in marker.parent.iterdir()] == ["backend.json"]
