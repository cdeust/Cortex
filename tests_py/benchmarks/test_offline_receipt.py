"""Issue #734, slice 6: memory operations with networking disabled.

The guard refuses every connection beyond the machine, a loopback proxy
included (the first receipt in a proxied container downloaded FlashRank
through ``127.0.0.1``), and the receipt labels each operation with the mode it
ran in.
"""

from __future__ import annotations

import asyncio
import errno
import socket

import pytest

from benchmarks.lib import offline_receipt
from benchmarks.lib.network_guard import NetworkGuard, is_local, proxy_endpoints
from benchmarks.lib.offline_receipt_ops import MEMORIES, _timed

# source: RFC 5737 (192.0.2.0/24 is TEST-NET-1, never routed).
_UNROUTED = ("192.0.2.1", 9)


@pytest.mark.parametrize(
    ("host", "local"),
    [
        (None, True),
        ("localhost", True),
        ("127.0.0.1", True),
        ("127.8.9.10", True),
        ("::1", True),
        (b"127.0.0.1", True),
        ("192.0.2.1", False),
        ("huggingface.co", False),
        ("::ffff:192.0.2.1", False),
    ],
)
def test_is_local_names_only_this_machine(host, local):
    assert is_local(host) is local


def test_guard_refuses_and_records_a_remote_connect():
    with NetworkGuard(proxies=frozenset()) as guard:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError) as raised:
                sock.connect(_UNROUTED)
            refused_ex = sock.connect_ex(_UNROUTED)
        finally:
            sock.close()
    assert raised.value.errno == errno.ENETUNREACH
    assert refused_ex == errno.ENETUNREACH
    assert guard.attempts == [
        {"call": "connect", "host": "192.0.2.1", "port": 9},
        {"call": "connect_ex", "host": "192.0.2.1", "port": 9},
    ]


def test_guard_refuses_a_lookup_and_allows_localhost():
    with NetworkGuard(proxies=frozenset()) as guard:
        with pytest.raises(OSError):
            socket.getaddrinfo("huggingface.co", 443)
        assert socket.getaddrinfo("localhost", 80)
    assert guard.attempts == [
        {"call": "getaddrinfo", "host": "huggingface.co", "port": 443}
    ]


def _listener() -> socket.socket:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    return server


def test_guard_allows_loopback_but_refuses_a_loopback_proxy():
    server = _listener()
    port = server.getsockname()[1]
    try:
        with NetworkGuard(proxies=frozenset()) as open_guard:
            with socket.create_connection(("127.0.0.1", port), timeout=5):
                pass
        assert open_guard.attempts == []
        with NetworkGuard(proxies=frozenset({("127.0.0.1", port)})) as guard:
            with pytest.raises(OSError):
                socket.create_connection(("127.0.0.1", port), timeout=5)
        assert guard.attempts == [
            {"call": "connect", "host": "127.0.0.1", "port": port}
        ]
    finally:
        server.close()


def test_uninstall_restores_the_socket_module():
    connect, lookup = socket.socket.connect, socket.getaddrinfo
    with NetworkGuard(proxies=frozenset()):
        assert socket.getaddrinfo is not lookup
    assert socket.socket.connect is connect
    assert socket.getaddrinfo is lookup


def test_proxy_endpoints_read_the_proxy_variables(monkeypatch):
    for key in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.upper(), raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:33051")
    monkeypatch.setenv("NO_PROXY", "localhost")
    assert ("127.0.0.1", 33051) in proxy_endpoints()


def test_child_env_moves_the_store_and_drops_proxies_and_pg(monkeypatch, tmp_path):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "localhost")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("PGHOST", "example")
    env = offline_receipt.child_env(tmp_path)
    assert not [key for key in env if key.lower().endswith("_proxy")]
    assert "DATABASE_URL" not in env and "PGHOST" not in env
    assert env["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"
    assert env["CORTEX_MEMORY_DB_PATH"].startswith(str(tmp_path))
    assert env["CORTEX_CLAUDE_DIR"] == str(tmp_path)


def _op(ok=True, mode="neural", reranker="loaded"):
    return {
        "operation": "recall",
        "ok": ok,
        "embedding_mode": mode,
        "reranker_state": reranker,
    }


@pytest.mark.parametrize(
    ("operations", "attempts", "expected"),
    [
        ([_op()], [], "offline"),
        ([_op()], [{"call": "connect", "host": "h", "port": 1}], "network_attempted"),
        ([_op(ok=False)], [{"call": "connect", "host": "h", "port": 1}], "failed"),
    ],
)
def test_verdict(operations, attempts, expected):
    found = offline_receipt.verdict(
        {"operations": operations, "network_attempts": attempts}
    )
    assert found == {"verdict": expected, "fallback": []}


def test_verdict_lists_fallback_operations():
    operations = [_op(), _op(mode="fallback"), _op(reranker="failed")]
    found = offline_receipt.verdict({"operations": operations, "network_attempts": []})
    assert [entry["index"] for entry in found["fallback"]] == [1, 2]


def test_an_operation_that_tries_the_network_is_counted():
    async def reaches_out():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect(_UNROUTED)
        finally:
            sock.close()

    with NetworkGuard(proxies=frozenset()) as guard:
        entry = asyncio.run(_timed(guard, "probe", reaches_out))
    assert entry["ok"] is False and entry["error"] == "OSError"
    assert entry["network_attempts"] == 1
    assert entry["embedding_mode"] in ("neural", "fallback")


def test_receipt_runs_memory_operations_offline(monkeypatch):
    # The offline switches a provisioned machine sets; with them nothing may
    # reach the network, whatever models are installed.
    monkeypatch.setenv("CORTEX_RERANKER_OFFLINE", "1")
    monkeypatch.setenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    receipt = offline_receipt.build_receipt()
    assert receipt["verdict"] == "offline", receipt["network_attempts"]
    operations = receipt["operations"]
    assert [op["operation"] for op in operations] == ["remember"] * len(MEMORIES) + [
        "recall"
    ]
    assert all(op["ok"] and op["network_attempts"] == 0 for op in operations)
    assert operations[-1]["result"]["found_stored"] is True
    for op in operations:
        assert op["embedding_mode"] in ("neural", "fallback")
        assert op["reranker_state"] in ("loaded", "failed", "not_attempted")
    assert receipt["runtime_manifest"]["backend"] == "sqlite"
    assert receipt["limits"]
