"""Failure diagnostics for the cross-host MCP protocol smoke test.

The parse boundary and the environment fixture moved to
``scripts/mcp_host_client.py`` along with the exchange itself; the
assertions are unchanged in intent. ``_responses(stdout: str)`` became
``absorb(line, responses)`` because the exchange now reads stdout one line
at a time — it cannot wait for the whole stream, since it must decide when
the batch is answered before closing stdin (see that module's docstring).
"""

from __future__ import annotations

import pytest

from scripts.mcp_host_client import ContractError, absorb, environment


def _absorb_all(stdout: str) -> dict[int, dict[str, object]]:
    responses: dict[int, dict[str, object]] = {}
    for line in stdout.splitlines():
        absorb(line, responses)
    return responses


def test_malformed_stdout_frame_is_reported_at_the_parse_boundary() -> None:
    with pytest.raises(ContractError, match="malformed JSON-RPC frame"):
        _absorb_all('{"jsonrpc":"2.0","id":1')


def test_non_object_stdout_frame_is_rejected() -> None:
    with pytest.raises(ContractError, match="non-object JSON-RPC frame"):
        _absorb_all("[]")


def test_valid_notification_is_ignored_but_response_is_retained() -> None:
    stdout = "\n".join(
        (
            '{"jsonrpc":"2.0","method":"notifications/initialized"}',
            '{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}',
        )
    )

    assert _absorb_all(stdout) == {
        2: {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}
    }


def test_default_environment_forces_the_isolated_sqlite_fixture(tmp_path) -> None:
    env = environment(tmp_path, socks_proxy_regression=False)

    assert env["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"


def test_auto_environment_cannot_inherit_a_forced_sqlite_backend(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CORTEX_ALLOW_SQLITE_FALLBACK", "1")

    env = environment(
        tmp_path,
        socks_proxy_regression=False,
        storage_selection="auto",
    )

    assert "CORTEX_MEMORY_STORE_BACKEND" not in env
    assert "CORTEX_ALLOW_SQLITE_FALLBACK" not in env


def test_a_blank_stdout_line_is_not_a_contract_error() -> None:
    """Line-at-a-time reading sees the trailing newline the old whole-stream
    ``splitlines()`` never produced; a blank line is not a malformed frame."""
    assert _absorb_all('\n{"jsonrpc":"2.0","id":1,"result":{}}\n\n') == {
        1: {"jsonrpc": "2.0", "id": 1, "result": {}}
    }
