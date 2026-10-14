"""scripts/launcher_backend.py: the first launch keeps an earlier local PostgreSQL.

Before ADR-1104 a marketplace install had no marker and ran on
``postgresql://localhost:5432/cortex`` through libpq. The review of #749 found
that such a user would have been moved to an empty SQLite store, and then that
a probe narrower than libpq (no PGUSER, no password file, no TLS) would still
move some of them. The decision now follows ``install-plugin.sh`` (ADR-0740)
the way libpq connected, against a fake server on a free port: these tests
never dial the real 5432.

source: ADR-1104
"""

from __future__ import annotations

import socket
import ssl
import struct
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import launcher_backend  # noqa: E402

_MARKER = "backend.json"


def _message(kind: bytes, payload: bytes) -> bytes:
    return kind + struct.pack("!i", len(payload) + 4) + payload


_AUTH_OK = _message(b"R", struct.pack("!i", 0))
_READY = _AUTH_OK + _message(b"S", b"a\x00b\x00") + _message(b"Z", b"I")
_NO_DATABASE = _AUTH_OK + _message(
    b"E", b'SFATAL\x00C3D000\x00Mdatabase "cortex" does not exist\x00\x00'
)
_PASSWORD = _message(b"R", struct.pack("!i", 10) + b"SCRAM-SHA-256\x00\x00")


def _recv(conn, size: int) -> bytes:
    data = b""
    while len(data) < size:
        data += conn.recv(size - len(data))
    return data


@pytest.fixture
def credentials_unset(monkeypatch, tmp_path):
    for name in ("PGUSER", "PGPASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PGPASSFILE", str(tmp_path / "no-pgpass"))


@pytest.fixture
def fake_server(monkeypatch, credentials_unset):
    """Serve one canned reply on a free port; record what the client sent."""
    servers = []

    def start(reply: bytes, tls: ssl.SSLContext | None = None) -> dict:
        listener = socket.create_server(("127.0.0.1", 0))
        seen: dict = {}

        def serve():
            conn, _ = listener.accept()
            seen["ssl_request"] = _recv(conn, 8)
            conn.sendall(b"S" if tls else b"N")
            if tls:
                conn = tls.wrap_socket(conn, server_side=True)
            with conn:
                length = struct.unpack("!i", _recv(conn, 4))[0]
                seen["startup"] = _recv(conn, length - 4)
                conn.sendall(reply)
                seen["after"] = conn.recv(5)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        seen["join"] = lambda: thread.join(timeout=5)
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
    methodology = tmp_path / "methodology"
    methodology.mkdir()
    (methodology / "backend.json.tmp1").write_text("")
    (methodology / ".DS_Store").write_text("")
    assert launcher_backend.decide(methodology, _MARKER) == ("sqlite", "fresh install")
    assert launcher_backend.decide(tmp_path / "absent", _MARKER)[0] == "sqlite"


def test_an_earlier_local_cortex_database_keeps_postgresql(tmp_path, fake_server):
    seen = fake_server(_READY)
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql", why
    assert seen["ssl_request"] == struct.pack("!ii", 8, 80877103)
    assert b"database\x00cortex\x00" in seen["startup"]
    seen["join"]()
    assert seen["after"] == b"X\x00\x00\x00\x04"


def test_pguser_names_the_user_as_libpq_did(tmp_path, fake_server, monkeypatch):
    seen = fake_server(_READY)
    monkeypatch.setenv("PGUSER", "cortex_owner")
    launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert b"user\x00cortex_owner\x00" in seen["startup"]


def test_a_server_that_offers_tls_is_reached_over_tls(tmp_path, fake_server):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert)],
        check=True, capture_output=True,
    )  # fmt: skip
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    seen = fake_server(_READY, tls)
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql", why
    assert b"database\x00cortex\x00" in seen["startup"]


def test_a_password_libpq_would_send_keeps_postgresql(
    tmp_path, fake_server, monkeypatch
):
    fake_server(_PASSWORD)
    monkeypatch.setenv("PGPASSWORD", "secret")
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "postgresql", why


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (_NO_DATABASE, 'database "cortex" does not exist'),
        (_PASSWORD, "asks for a password and none is set"),
    ],
)
def test_a_database_that_does_not_open_is_sqlite_with_the_reason(
    tmp_path, fake_server, reply, reason
):
    fake_server(reply)
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite"
    assert reason in why and "set database_url" in why


def test_a_malformed_reply_is_a_reason_not_a_traceback(tmp_path, fake_server):
    fake_server(b"Z\x00\x00\x00\x02")  # length shorter than its own field
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite" and "no database answered" in why


def test_nothing_listening_is_sqlite_with_the_reason(
    tmp_path, monkeypatch, credentials_unset
):
    with socket.create_server(("127.0.0.1", 0)) as unused:
        port = unused.getsockname()[1]
    monkeypatch.setattr(launcher_backend, "LEGACY_HOST", "127.0.0.1")
    monkeypatch.setattr(launcher_backend, "LEGACY_PORT", port)
    backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite"
    assert "no database answered" in why


def test_a_silent_server_is_bounded_as_a_whole(
    tmp_path, monkeypatch, credentials_unset
):
    listener = socket.create_server(("127.0.0.1", 0))  # accepts, never answers
    monkeypatch.setattr(launcher_backend, "LEGACY_HOST", "127.0.0.1")
    monkeypatch.setattr(launcher_backend, "LEGACY_PORT", listener.getsockname()[1])
    monkeypatch.setattr(launcher_backend, "PROBE_SECONDS", 0.5)
    with listener:
        backend, why = launcher_backend.decide(_earlier_state(tmp_path), _MARKER)
    assert backend == "sqlite"
    assert "timed out" in why or "no answer" in why


def test_the_decision_is_recorded_and_printed(tmp_path, monkeypatch, capsys):
    from mcp_server.infrastructure import backend_marker

    marker = tmp_path / "methodology" / "backend.json"
    monkeypatch.setattr(backend_marker, "BACKEND_MARKER_PATH", marker)
    launcher_backend.persist_first_decision()
    assert backend_marker.read_backend_marker(marker)["backend"] == "sqlite"
    assert "storage: sqlite (fresh install)" in capsys.readouterr().err
    assert [p.name for p in marker.parent.iterdir()] == ["backend.json"]
