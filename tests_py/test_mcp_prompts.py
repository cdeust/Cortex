"""Tests for MCP prompts (prompts/list + prompts/get), issue #176."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP
from mcp.shared.exceptions import McpError

from mcp_server import mcp_prompts, tool_profiles
from mcp_server.__main__ import merged_schemas, register_all
from mcp_server.tool_profile_middleware import ToolProfileMiddleware
from mcp_server.tool_profiles import ToolProfile


def _build(profile: ToolProfile) -> FastMCP:
    server = FastMCP(
        name="t", version="0", instructions=tool_profiles.instructions(profile)
    )
    register_all(server, codebase=False, prd=False)
    mcp_prompts.register_prompts(server, merged_schemas())
    server.add_middleware(ToolProfileMiddleware(profile))
    return server


def _run(server: FastMCP, coro_fn):
    async def go():
        async with Client(server) as client:
            return await coro_fn(client)

    return asyncio.run(go())


# ── source of truth (criterion 3) ───────────────────────────────────────────


def test_every_prompt_step_names_a_real_tool():
    """A prompt step must name a tool present in the merged schema map — the
    same source of truth as tools/list. Drift here is the #98 defect class."""
    schemas = merged_schemas()
    for name in mcp_prompts.PROMPT_NAMES:
        for tool in mcp_prompts.required_tools(name):
            assert tool in schemas, f"prompt {name} references unknown tool {tool}"


def test_tool_summary_comes_from_schema_description():
    schemas = merged_schemas()
    summary = mcp_prompts.tool_summary(schemas, "recall")
    assert summary
    assert schemas["recall"]["description"].startswith(summary.rstrip("."))


# ── prompts/list per profile (criteria 1, 2) ────────────────────────────────


def test_full_lists_all_three_prompts():
    server = _build(ToolProfile.FULL)
    names = {p.name for p in _run(server, lambda c: c.list_prompts())}
    assert names == {"session_recall", "promote_memories", "curate_wiki"}


def test_lean_lists_only_session_recall():
    # promote_memories and curate_wiki drive full-only tools, so lean hides them.
    server = _build(ToolProfile.LEAN)
    names = {p.name for p in _run(server, lambda c: c.list_prompts())}
    assert names == {"session_recall"}


def test_every_argument_has_name_description_required():
    server = _build(ToolProfile.FULL)
    prompts = _run(server, lambda c: c.list_prompts())
    for prompt in prompts:
        for arg in prompt.arguments:
            assert arg.name
            assert arg.description  # human title folded into the description
            assert isinstance(arg.required, bool)


# ── prompts/get render (criterion 1) ────────────────────────────────────────


def test_get_session_recall_embeds_args_and_canonical_summary():
    server = _build(ToolProfile.FULL)
    schemas = merged_schemas()

    async def call(c):
        return await c.get_prompt(
            "session_recall", {"project": "/repo", "focus": "auth"}
        )

    result = _run(server, call)
    text = result.messages[0].content.text
    assert "/repo" in text
    assert "auth" in text
    assert "`query_methodology`" in text
    assert mcp_prompts.tool_summary(schemas, "query_methodology") in text


def test_get_promote_memories_available_under_full():
    server = _build(ToolProfile.FULL)

    async def call(c):
        return await c.get_prompt("promote_memories", {})

    result = _run(server, call)
    assert "`consolidate`" in result.messages[0].content.text


# ── failure arms (criterion 6 / §13 A3) ─────────────────────────────────────


def test_unknown_prompt_name_errors():
    server = _build(ToolProfile.FULL)

    async def call(c):
        return await c.get_prompt("no_such_prompt", {})

    with pytest.raises(McpError):
        _run(server, call)


def test_missing_required_argument_errors():
    server = _build(ToolProfile.FULL)

    async def call(c):
        return await c.get_prompt("session_recall", {})  # 'project' required

    with pytest.raises(McpError):
        _run(server, call)


def test_full_only_prompt_rejected_under_lean():
    server = _build(ToolProfile.LEAN)

    async def call(c):
        return await c.get_prompt("promote_memories", {})

    with pytest.raises(Exception) as exc:
        _run(server, call)
    assert (
        "profile" in str(exc.value).lower()
        or "unknown prompt" in str(exc.value).lower()
    )


def test_is_available_matches_profile_membership():
    assert mcp_prompts.is_available("session_recall", ToolProfile.LEAN)
    assert mcp_prompts.is_available("session_recall", ToolProfile.FULL)
    assert not mcp_prompts.is_available("promote_memories", ToolProfile.LEAN)
    assert mcp_prompts.is_available("promote_memories", ToolProfile.FULL)
    assert not mcp_prompts.is_available("no_such_prompt", ToolProfile.FULL)
