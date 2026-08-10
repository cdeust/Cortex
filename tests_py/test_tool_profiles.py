"""Tests for MCP tool profiles + the profile-enforcement middleware (#177)."""

from __future__ import annotations

import asyncio

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from mcp_server import mcp_prompts, tool_profiles
from mcp_server.__main__ import merged_schemas, register_all
from mcp_server.tool_profile_middleware import ToolProfileMiddleware
from mcp_server.tool_profiles import ToolProfile

# Destructive tools that MUST be excluded from lean and rejected on call
# (issue #177 criterion 5). source: annotations.destructiveHint in the
# handler schemas + docs/mcp-tools.md.
_DESTRUCTIVE = {"forget", "wiki_purge", "wiki_migrate"}


def _build(profile: ToolProfile) -> MCPServer:
    # ToolProfileMiddleware must be passed at construction (mcp 2.0.0's
    # `middleware` list is constructor-only — no post-construction
    # `add_middleware`, unlike FastMCP; see tool_profile_middleware.py's
    # module docstring and mcp_server/__main__.py's Server Instance
    # section for the same pattern in the composition root).
    server = MCPServer(
        name="t",
        version="0",
        instructions=tool_profiles.instructions(profile),
        middleware=[ToolProfileMiddleware(profile)],
    )
    register_all(server, codebase=False, prd=False)
    mcp_prompts.register_prompts(server, merged_schemas())
    return server


def _run(server: MCPServer, coro_fn):
    async def go():
        async with Client(server) as client:
            return await coro_fn(client)

    return asyncio.run(go())


# ── resolve / parse (criterion 7: unknown profile name) ─────────────────────


class TestResolve:
    def test_default_is_full(self):
        assert tool_profiles.resolve(argv=[], env={}) is ToolProfile.FULL

    def test_env_selects_lean(self):
        assert (
            tool_profiles.resolve(argv=[], env={"CORTEX_MCP_PROFILE": "lean"})
            is ToolProfile.LEAN
        )

    def test_flag_wins_over_env(self):
        got = tool_profiles.resolve(
            argv=["--profile", "full"], env={"CORTEX_MCP_PROFILE": "lean"}
        )
        assert got is ToolProfile.FULL

    def test_equals_spelling(self):
        assert (
            tool_profiles.resolve(argv=["--profile=lean"], env={}) is ToolProfile.LEAN
        )

    def test_unknown_profile_name_raises(self):
        with pytest.raises(ValueError):
            tool_profiles.resolve(argv=[], env={"CORTEX_MCP_PROFILE": "bogus"})

    def test_flag_without_value_raises(self):
        with pytest.raises(ValueError):
            tool_profiles.resolve(argv=["--profile"], env={})


# ── allows (criterion 7: tool allowed / excluded) ───────────────────────────


class TestAllows:
    def test_full_allows_everything(self):
        assert tool_profiles.allows(ToolProfile.FULL, "forget")
        assert tool_profiles.allows(ToolProfile.FULL, "anything_at_all")

    def test_lean_allows_only_the_set(self):
        assert tool_profiles.allows(ToolProfile.LEAN, "recall")
        assert not tool_profiles.allows(ToolProfile.LEAN, "forget")

    def test_lean_excludes_every_destructive_tool(self):
        for name in _DESTRUCTIVE:
            assert not tool_profiles.allows(ToolProfile.LEAN, name), name

    def test_instructions_differ_by_profile(self):
        full = tool_profiles.instructions(ToolProfile.FULL)
        lean = tool_profiles.instructions(ToolProfile.LEAN)
        assert full != lean
        assert "query_methodology" in full and "query_methodology" in lean
        assert "full" in full.lower() and "lean" in lean.lower()


# ── list filtering + call gating (criteria 4, 5, 7) ─────────────────────────


class TestSurface:
    def test_full_lists_all_52_tools(self):
        server = _build(ToolProfile.FULL)
        names = _run(server, lambda c: c.list_tools()).tools
        assert len({t.name for t in names}) == 52

    def test_lean_lists_exactly_the_lean_set(self):
        server = _build(ToolProfile.LEAN)
        names = {t.name for t in _run(server, lambda c: c.list_tools()).tools}
        assert names == set(tool_profiles.LEAN_TOOL_NAMES)

    def test_lean_hides_and_rejects_destructive_calls(self):
        # criterion 5: gated, not merely hidden.
        #
        # NOT pytest.raises(Exception): mcp.Client.call_tool() does not
        # raise on isError=True (unlike fastmcp.Client, which did) — it
        # returns a CallToolResult the caller inspects. That is the
        # deliberate wire shape ToolProfileMiddleware produces for a
        # rejected tools/call (see its module docstring point 2): a
        # graceful, model-visible tool error, not a protocol-level
        # exception — mirroring how the tool's own handler failures are
        # reported (tool_error_handler.py's whole design), so a rejected
        # call looks like any other tool error to the client.
        server = _build(ToolProfile.LEAN)
        names = {t.name for t in _run(server, lambda c: c.list_tools()).tools}
        for tool in _DESTRUCTIVE:
            assert tool not in names, f"{tool} should be hidden under lean"

            async def call(c, _tool=tool):
                return await c.call_tool(_tool, {})

            result = _run(server, call)
            assert result.is_error, f"{tool} should be rejected under lean"
            message = result.content[0].text.lower()
            assert "profile" in message or "unknown tool" in message

    def test_full_does_not_reject_or_hide(self):
        server = _build(ToolProfile.FULL)
        names = {t.name for t in _run(server, lambda c: c.list_tools()).tools}
        assert _DESTRUCTIVE <= names
