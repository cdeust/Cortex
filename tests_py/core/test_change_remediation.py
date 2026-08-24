"""Unit tests for the pure change-remediation classifier (#110)."""

from __future__ import annotations

from dataclasses import dataclass

from mcp_server.core.change_remediation import (
    Remediation,
    build_impacted,
    classify_remediation,
    is_code_derived,
)


@dataclass
class _Match:
    memory_id: int
    matched_files: list[str]


def test_build_impacted_attaches_changed_refs() -> None:
    matches = [_Match(1, ["src/a.py", "src/b.py"]), _Match(2, ["src/c.py"])]
    memory_by_id = {1: {"id": 1, "content": "x"}, 2: {"id": 2, "content": "y"}}
    impacted = build_impacted(matches, memory_by_id)
    assert impacted[0]["changed_refs"] == ["src/a.py", "src/b.py"]
    assert impacted[0]["content"] == "x"  # memory fields preserved
    assert impacted[1]["changed_refs"] == ["src/c.py"]


def test_build_impacted_drops_unknown_memory() -> None:
    matches = [_Match(1, ["src/a.py"]), _Match(99, ["src/z.py"])]
    impacted = build_impacted(matches, {1: {"id": 1}})
    assert [m["id"] for m in impacted] == [1]  # id 99 has no memory → dropped


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
