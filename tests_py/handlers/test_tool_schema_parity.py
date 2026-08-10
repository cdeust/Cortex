"""Input-schema parity between handler schemas and registered MCP wrappers
(#98 regression guard).

The client-visible input schema is whatever the MCP SDK derives from the
REGISTERED WRAPPER's signature (``tool_registry_*.py``), not from the
handler's own ``schema["inputSchema"]`` dict. If a handler gains a new
parameter (or an enum value) but the wrapper signature is never updated
to match, the parameter silently becomes unreachable over MCP even
though the handler-level schema documents it. This test asserts, for
each tool checked, that every property the handler's own inputSchema
declares is actually present on the live registered wrapper's parameter
set — i.e. handler properties are a SUBSET of wrapper parameters.

This must FAIL on the pre-#98 code (remember was missing supersedes_id
+ write_class; wiki_write was missing memory_ids) and PASS after.
"""

from __future__ import annotations

import asyncio

from mcp_server.__main__ import mcp
from mcp_server.handlers import remember, wiki_write
from mcp_server.infrastructure.memory_config import root_agent_topic

# agent_topic is DELIBERATELY omitted from the "rooted" remember/recall
# wrapper variant when CORTEX_ROOT_AGENT_TOPIC is set (server forces the
# scope instead) — see tool_registry_memory.py::_register_remember. When
# a test environment happens to run rooted, exclude it here rather than
# mask that as a #98-style regression; unrooted (the default in this
# suite) exposes agent_topic and the exclusion set is empty.
_ROOTED_OMISSIONS: set[str] = (
    {"agent_topic"} if root_agent_topic() is not None else set()
)


def _live_wrapper_params(tool_name: str) -> set[str]:
    """Return the parameter names the MCP SDK actually derived for
    `tool_name` from the registered wrapper's signature — the
    client-visible truth. Reads ``.input_schema`` (the wire-level
    ``mcp.types.Tool`` field mcp 2.0.0 uses — was ``.parameters`` under
    FastMCP; verified against the installed mcp==2.0.0, 2026-08-10)."""
    tools = asyncio.run(mcp.list_tools())
    matches = [t for t in tools if t.name == tool_name]
    assert matches, f"tool {tool_name!r} not registered"
    return set(matches[0].input_schema.get("properties", {}).keys())


def _assert_handler_properties_are_subset(
    tool_name: str, handler_schema: dict, omit: set[str] | None = None
) -> None:
    handler_props = set(handler_schema["inputSchema"]["properties"].keys())
    wrapper_params = _live_wrapper_params(tool_name)
    omit = omit or set()
    missing = (handler_props - omit) - wrapper_params
    assert not missing, (
        f"{tool_name}: handler schema declares {sorted(missing)} but the "
        f"registered wrapper signature does not expose them — client-"
        f"visible MCP schema has drifted from the handler contract "
        f"(#98). Wrapper params: {sorted(wrapper_params)}"
    )


class TestRememberSchemaParity:
    def test_remember_wrapper_exposes_all_handler_properties(self):
        # is_global/created_at/initial_heat are pre-existing, out-of-scope
        # drift (not part of #98's confirmed issue set) — excluded so this
        # test targets exactly the #98 regression (supersedes_id, write_class)
        # without asserting on unrelated, separately-tracked drift.
        _assert_handler_properties_are_subset(
            "remember",
            remember.schema,
            omit={"is_global", "created_at", "initial_heat"} | _ROOTED_OMISSIONS,
        )

    def test_remember_exposes_supersedes_id(self):
        assert "supersedes_id" in _live_wrapper_params("remember")

    def test_remember_exposes_write_class(self):
        assert "write_class" in _live_wrapper_params("remember")


class TestWikiWriteSchemaParity:
    def test_wiki_write_wrapper_exposes_all_handler_properties(self):
        # title/body/summary (template-rendering params, wiki_write.py
        # schema ~:111-124) are PRE-EXISTING drift not part of the
        # confirmed #98 issue set (which named only memory_ids) — excluded
        # so this test targets exactly the #98 regression without
        # asserting on separately-tracked, unconfirmed drift.
        _assert_handler_properties_are_subset(
            "wiki_write",
            wiki_write.schema,
            omit={"title", "body", "summary"},
        )

    def test_wiki_write_exposes_memory_ids(self):
        assert "memory_ids" in _live_wrapper_params("wiki_write")
