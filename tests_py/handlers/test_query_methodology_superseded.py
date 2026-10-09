"""query_methodology never lists a superseded memory among hotMemories.

Observed 2026-10-09: after ``remember(..., supersedes_id=4383843, force=True)``
returned ``"action":"superseded"``, ``query_methodology`` listed BOTH the new
head and the retracted row in ``hotMemories``. Runs the real store (in-memory
SQLite), no mocks: the query that picks the rows is the subject.
"""

from __future__ import annotations

import asyncio
from unittest.mock import Mock, patch

import pytest

from mcp_server.handlers import query_methodology as methodology
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_DOMAIN = "supersession-hot-memories"
_DIRECTORY = "/fixture/project"


@pytest.fixture
def store():
    s = SqliteMemoryStore()
    old_id = s.insert_memory(
        {
            "content": "personal profile: lives in Lyon",
            "domain": _DOMAIN,
            "directory_context": _DIRECTORY,
            "heat": 0.9,
            "source": "user",
        }
    )
    new_id, head = s.supersede_atomic(
        {
            "content": "personal profile: lives in Paris",
            "domain": _DOMAIN,
            "directory_context": _DIRECTORY,
            "heat": 0.9,
            "source": "user",
        },
        old_id,
    )
    assert head == old_id
    s.old_id, s.new_id = old_id, new_id  # type: ignore[attr-defined]
    return s


def _ids(store, domain, directory):
    with patch.object(methodology, "_try_get_memory_store", return_value=store):
        return [m["id"] for m in methodology._get_hot_memories(domain, directory)]


@pytest.mark.parametrize(
    ("domain", "directory"),
    [(_DOMAIN, ""), ("", _DIRECTORY), ("", "")],
    ids=["domain", "directory", "global"],
)
def test_superseded_row_is_excluded_and_the_head_is_returned(store, domain, directory):
    ids = _ids(store, domain, directory)
    assert store.new_id in ids
    assert store.old_id not in ids


def test_handler_hot_memories_exclude_the_superseded_row(store):
    with patch.multiple(
        methodology,
        load_profiles=Mock(return_value={}),
        detect_domain=Mock(return_value={"domain": _DOMAIN}),
        _try_get_memory_store=Mock(return_value=store),
        _get_fired_triggers=Mock(return_value=[]),
    ):
        with patch("mcp_server.core.telemetry.record"):
            result = asyncio.run(methodology.handler({"cwd": _DIRECTORY}))
    ids = [m["id"] for m in result["hotMemories"]]
    assert ids == [store.new_id]
