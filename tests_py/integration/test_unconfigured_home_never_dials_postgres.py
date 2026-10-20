"""A HOME nothing configures never dials PostgreSQL, from any entry point (#703, #704).

Measured on main df3a447 (2026-10-20, fresh HOME, no marker, no URL): the
launcher's hook dialed nothing, but the wheel's hook entry
(``python -m mcp_server.hooks.entry``) and the server (``python -m mcp_server``)
each opened a TCP connection to ``127.0.0.1:5432``, and ``remember`` failed
with "Cortex requires PostgreSQL in CLI mode". Each entry point now runs in a
subprocess while this test listens on ``127.0.0.1:5432`` and counts every
connection (libpq dials from C, below any Python-level guard). When the port
is taken (a real PostgreSQL, e.g. the PostgreSQL CI job) the test skips: that
server is exactly what an unconfigured HOME must never reach.

source: ADR-1110
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_PG_PORT = 5432  # source: ADR-1104 legacy URL port, the one the defect dialed
_CLEARED_PREFIXES = ("PG", "DATABASE_URL", "CORTEX_", "CLAUDE_")


@pytest.fixture
def pg_port_listener():
    """Count connections to 127.0.0.1:5432; skip when something already owns it."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("127.0.0.1", _PG_PORT))
    except OSError as exc:
        server.close()
        pytest.skip(f"127.0.0.1:{_PG_PORT} is in use ({exc}); cannot prove no dial")
    server.listen(16)
    server.settimeout(0.2)
    seen: list[tuple] = []
    stop = threading.Event()

    def accept_loop() -> None:
        while not stop.is_set():
            try:
                conn, addr = server.accept()
            except OSError:
                continue
            seen.append(addr)
            conn.close()

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    yield seen
    stop.set()
    thread.join(timeout=2)
    server.close()


def _env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(_CLEARED_PREFIXES)}
    env.update(
        HOME=str(tmp_path / "home"),
        CORTEX_CLAUDE_DIR=str(tmp_path / "home" / ".claude"),
        PYTHONPATH=str(REPO_ROOT),
        CORTEX_AUTO_INSTALL_PIPELINE="0",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    return env


def _marker(tmp_path: Path) -> dict:
    path = tmp_path / "home" / ".claude" / "methodology" / "backend.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("hook", ["session_start", "auto_recall"])
def test_wheel_hook_entry_uses_sqlite_and_dials_nothing(
    tmp_path, hook, pg_port_listener
):
    event = {"session_id": "t", "cwd": str(tmp_path), "prompt": "how does recall work"}
    result = subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.entry", hook],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=_env(tmp_path),
        cwd=tmp_path,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert pg_port_listener == [], result.stderr[-2000:]
    assert _marker(tmp_path)["backend"] == "sqlite"


def test_server_remember_works_on_sqlite_and_dials_nothing(tmp_path, pg_port_listener):
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "remember",
                "arguments": {"content": "unconfigured home stores on sqlite"},
            },
        },
    ]
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp_path),
        cwd=tmp_path,
    )
    reply = _call_remember(proc, requests)
    assert reply is not None, "server never answered remember"
    assert not reply["result"].get("isError"), reply
    assert pg_port_listener == []
    assert _marker(tmp_path)["backend"] == "sqlite"


def _call_remember(proc: subprocess.Popen, requests: list[dict]) -> dict | None:
    assert proc.stdin is not None and proc.stdout is not None
    try:
        for message in requests:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        for line in proc.stdout:
            payload = json.loads(line)
            if payload.get("id") == 2:
                return payload
        return None
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
