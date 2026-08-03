"""Failure diagnostics for the cross-host MCP protocol smoke test."""

from __future__ import annotations

import pytest

from scripts.verify_mcp_hosts import ContractError, _environment, _responses


def test_malformed_stdout_frame_is_reported_at_the_parse_boundary() -> None:
    with pytest.raises(ContractError, match="malformed JSON-RPC frame"):
        _responses('{"jsonrpc":"2.0","id":1')


def test_non_object_stdout_frame_is_rejected() -> None:
    with pytest.raises(ContractError, match="non-object JSON-RPC frame"):
        _responses("[]")


def test_valid_notification_is_ignored_but_response_is_retained() -> None:
    stdout = "\n".join(
        (
            '{"jsonrpc":"2.0","method":"notifications/initialized"}',
            '{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}',
        )
    )

    assert _responses(stdout) == {
        2: {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}
    }


def test_default_environment_forces_the_isolated_sqlite_fixture(tmp_path) -> None:
    env = _environment(tmp_path, socks_proxy_regression=False)

    assert env["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"


def test_auto_environment_cannot_inherit_a_forced_sqlite_backend(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CORTEX_ALLOW_SQLITE_FALLBACK", "1")

    env = _environment(
        tmp_path,
        socks_proxy_regression=False,
        storage_selection="auto",
    )

    assert "CORTEX_MEMORY_STORE_BACKEND" not in env
    assert "CORTEX_ALLOW_SQLITE_FALLBACK" not in env
