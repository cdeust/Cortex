"""``apply_input_constraints`` (ADR-1093): what it publishes, what it refuses.

Each keyword it publishes (anyOf, oneOf, allOf, dependentRequired) is read back
through ``list_tools()``, the client-visible truth; every refusal is a
``ValueError`` so a constraint is never dropped silently (#661).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from mcp_server.handlers._tool_meta import (
    CONSTRAINT_KEYWORDS,
    apply_input_constraints,
)


def _server() -> MCPServer:
    server = MCPServer(name="constraints", version="0.0.0")

    @server.tool()
    def probe(a: int | None = None, b: int | None = None) -> int:
        return 0

    return server


def _publish(declared: dict[str, Any]) -> dict[str, Any]:
    server = _server()
    apply_input_constraints(server, {"probe": {"inputSchema": declared}})
    return asyncio.run(server.list_tools())[0].input_schema


_BRANCHES = [{"required": ["a"]}, {"required": ["b"]}]
_PUBLISHED = {
    "anyOf": _BRANCHES,
    "oneOf": _BRANCHES,
    "allOf": _BRANCHES,
    "dependentRequired": {"a": ["b"]},
}


@pytest.mark.parametrize("keyword", CONSTRAINT_KEYWORDS)
def test_each_keyword_is_published_as_an_independent_copy(keyword: str) -> None:
    declared = {keyword: _PUBLISHED[keyword]}
    published = _publish(declared)
    assert published[keyword] == declared[keyword]
    assert published[keyword] is not declared[keyword]


def test_required_is_never_copied() -> None:
    published = _publish({"required": ["a"], "anyOf": _BRANCHES})
    assert "required" not in published


@pytest.mark.parametrize("keyword", ["not", "if", "then", "else", "contains"])
def test_unpublishable_root_keyword_is_refused(keyword: str) -> None:
    with pytest.raises(
        ValueError, match=rf"probe: unpublishable keywords \['{keyword}'\]"
    ):
        _publish({keyword: {"required": ["a"]}})


@pytest.mark.parametrize(
    "declared",
    [
        {"anyOf": [{"required": ["zzz"]}]},
        {"oneOf": [{"properties": {"zzz": {"type": "string"}}}]},
        {"allOf": [{"required": ["a"], "properties": {"zzz": {}}}]},
        {"dependentRequired": {"a": ["zzz"]}},
        {"dependentRequired": {"zzz": ["a"]}},
    ],
)
def test_unexposed_property_is_refused_wherever_it_is_mentioned(
    declared: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match=r"does not expose"):
        _publish(declared)


def test_unchecked_branch_keyword_is_refused() -> None:
    with pytest.raises(ValueError, match=r"unchecked \['not'\]"):
        _publish({"anyOf": [{"required": ["a"], "not": {"required": ["b"]}}]})
