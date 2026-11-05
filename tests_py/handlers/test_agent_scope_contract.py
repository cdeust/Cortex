"""Issue #718, slice 1: the agent-scope contract as it is today, end to end.

``agent_topic`` (and ``CORTEX_ROOT_AGENT_TOPIC``) is a ranking boost on
search, not an eligibility filter: a recall scoped to one agent still returns
another agent's memories. Only fetch-by-id under a rooted connection enforces
the scope. ``docs/agent-scope.md`` states this per surface; these tests pin
it through real SQLite persistence so the document cannot drift from the code
without a red test. Whether to offer a private scope is the owner's decision
(issue #718); a change to that contract must change these tests.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.handlers import recall, remember
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_ENV = "CORTEX_ROOT_AGENT_TOPIC"
_QUERY = "issue 718 lighthouse calibration procedure"


@pytest.fixture
def two_agents(tmp_path, monkeypatch):
    """One SQLite store holding one memory for each of two agent topics."""
    monkeypatch.delenv(_ENV, raising=False)
    store = SqliteMemoryStore(str(tmp_path / "agent_scope.db"))
    monkeypatch.setattr(remember, "_store", store)
    monkeypatch.setattr(recall, "_store", store)
    ids = {}
    for agent in ("alpha", "beta"):
        result = asyncio.run(
            remember.handler(
                {
                    "content": f"{_QUERY}: step recorded by agent {agent}",
                    "agent_topic": agent,
                    "force": True,
                }
            )
        )
        assert result["stored"] is True, result
        ids[agent] = result["memory_id"]
    try:
        yield ids
    finally:
        store.close()


def _recalled_ids(args: dict) -> set[int]:
    result = asyncio.run(recall.handler({"min_heat": 0.0, **args}))
    # Search results carry ``memory_id``; a fetch-by-id returns the stored row,
    # keyed ``id``.
    return {m.get("memory_id", m.get("id")) for m in result["memories"]}


def test_remember_tags_each_memory_with_its_agent(two_agents):
    store = recall._get_store()
    for agent, memory_id in two_agents.items():
        assert store.get_memory(memory_id)["agent_context"] == agent


def test_agent_topic_recall_still_returns_other_agents(two_agents):
    """agent_topic boosts; it does not restrict (both backends, ADR-0616)."""
    found = _recalled_ids({"query": _QUERY, "agent_topic": "alpha"})
    assert {two_agents["alpha"], two_agents["beta"]} <= found


def test_rooted_recall_search_still_returns_other_agents(two_agents, monkeypatch):
    monkeypatch.setenv(_ENV, "alpha")
    found = _recalled_ids({"query": _QUERY})
    assert two_agents["beta"] in found


def test_rooted_fetch_by_id_hides_other_agents(two_agents, monkeypatch):
    monkeypatch.setenv(_ENV, "alpha")
    assert _recalled_ids({"memory_id": two_agents["alpha"]}) == {two_agents["alpha"]}
    assert _recalled_ids({"memory_id": two_agents["beta"]}) == set()


def test_unrooted_fetch_by_id_ignores_agent_topic(two_agents):
    found = _recalled_ids({"memory_id": two_agents["beta"], "agent_topic": "alpha"})
    assert found == {two_agents["beta"]}
