"""Connection-rooted scoping (borrow-from-supermemory item 2).

When the server is launched with ``CORTEX_ROOT_AGENT_TOPIC`` set, the
``agent_topic`` parameter is (1) stripped from the registered recall/remember
tool schemas — so the model never sees it — and (2) forced server-side in the
handlers regardless of what any caller passes. This mirrors supermemory's
``x-sm-project`` capability header: the model cannot target, or accidentally
omit, another agent's scope.

External signals (handover acceptance):
  - the ``agent_topic`` field is absent from the tool schema JSON when rooted,
    and present when unrooted;
  - a rooted recall forwards the ROOT topic to retrieval even when the caller
    passes a different one (cannot cross scopes).
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP

from mcp_server import tool_registry_memory
from mcp_server.handlers import recall, remember

_ROOT = "rooted-agent-x"
_ENV = "CORTEX_ROOT_AGENT_TOPIC"


def _recall_param_props() -> dict:
    mcp = FastMCP("test")
    tool_registry_memory.register(mcp)
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "recall")
    return (tool.parameters or {}).get("properties", {})


def _remember_param_props() -> dict:
    mcp = FastMCP("test")
    tool_registry_memory.register(mcp)
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == "remember")
    return (tool.parameters or {}).get("properties", {})


def test_unrooted_exposes_agent_topic(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    assert "agent_topic" in _recall_param_props()
    assert "agent_topic" in _remember_param_props()


def test_rooted_strips_agent_topic_from_schema(monkeypatch):
    monkeypatch.setenv(_ENV, _ROOT)
    assert "agent_topic" not in _recall_param_props()
    assert "agent_topic" not in _remember_param_props()
    # The rest of the surface is unchanged.
    assert "query" in _recall_param_props()
    assert "content" in _remember_param_props()


def test_rooted_recall_forces_root_topic(monkeypatch):
    """A rooted recall forwards the ROOT topic to retrieval even when the
    caller passes a different scope — it cannot cross scopes."""
    monkeypatch.setenv(_ENV, _ROOT)
    captured: dict = {}

    def _fake_pg_recall(*_a, **kw):
        captured["agent_topic"] = kw.get("agent_topic")
        return []

    monkeypatch.setattr(recall, "pg_recall", _fake_pg_recall)
    asyncio.run(
        recall.handler({"query": "anything", "agent_topic": "some-other-agent"})
    )
    assert captured["agent_topic"] == _ROOT


def test_unrooted_recall_honors_caller_topic(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    captured: dict = {}

    def _fake_pg_recall(*_a, **kw):
        captured["agent_topic"] = kw.get("agent_topic")
        return []

    monkeypatch.setattr(recall, "pg_recall", _fake_pg_recall)
    asyncio.run(recall.handler({"query": "anything", "agent_topic": "caller-agent"}))
    assert captured["agent_topic"] == "caller-agent"


def test_rooted_remember_forces_root_topic(monkeypatch):
    """The remember handler overwrites args['agent_topic'] with the root
    before arg-parsing, so a write cannot land in another agent's scope."""
    monkeypatch.setenv(_ENV, _ROOT)
    captured: dict = {}

    class _StopParseError(Exception):
        pass

    def _fake_parse_args(args):
        captured["agent_topic"] = args.get("agent_topic")
        raise _StopParseError

    monkeypatch.setattr(remember, "_parse_args", _fake_parse_args)
    with pytest.raises(_StopParseError):
        asyncio.run(
            remember.handler(
                {"content": "a durable fact", "agent_topic": "some-other-agent"}
            )
        )
    assert captured["agent_topic"] == _ROOT
