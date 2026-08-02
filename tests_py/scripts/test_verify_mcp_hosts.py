"""Failure diagnostics for the cross-host MCP protocol smoke test."""

from __future__ import annotations

import pytest

from scripts.verify_mcp_hosts import ContractError, _responses


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
