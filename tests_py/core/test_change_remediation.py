"""Unit tests for the pure change-remediation classifier (#110)."""

from __future__ import annotations

from mcp_server.core.change_remediation import (
    Remediation,
    classify_remediation,
    is_code_derived,
)


def test_code_derived_by_agent_context() -> None:
    assert is_code_derived({"agent_context": "codebase"})
    assert classify_remediation({"agent_context": "codebase"}) is Remediation.REINGEST


def test_code_derived_by_tags() -> None:
    assert is_code_derived({"tags": ["codebase"]})
    assert is_code_derived({"tags": ["hash:abc123"]})


def test_hand_authored_is_flag_stale() -> None:
    mem = {"agent_context": "", "tags": ["decision"], "content": "we chose X"}
    assert not is_code_derived(mem)
    assert classify_remediation(mem) is Remediation.FLAG_STALE


def test_missing_fields_default_to_flag_stale() -> None:
    assert classify_remediation({}) is Remediation.FLAG_STALE
