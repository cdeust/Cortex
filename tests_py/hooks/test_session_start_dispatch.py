"""What ``_session_start`` hands each collaborator (ADR-1122 mutation gate, #711).

The other main() tests stub the collaborators and look at the printed result,
so a call that passed ``None`` instead of the event or the project root went
unnoticed. These tests pin the arguments themselves."""

from __future__ import annotations

import os
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from mcp_server.hooks import session_start as hook

EVENT = {"session_id": "s-1", "cwd": "/the/project"}
ROOT = "/the/project"


def _run(**overrides):
    """Run ``_session_start`` with every collaborator a MagicMock; return them."""
    mocks = {
        "harden_at_startup": MagicMock(),
        "_read_event": MagicMock(return_value=EVENT),
        "_refresh_session_registry": MagicMock(),
        "resolve_project_root": MagicMock(return_value=ROOT),
        "_auto_wire_pipeline": MagicMock(),
        "_maybe_background_reanalyze": MagicMock(),
        "_maybe_background_prune_graphs": MagicMock(),
        "_maybe_background_consolidate": MagicMock(),
        "_backend_is_sqlite": MagicMock(return_value=False),
        "_sqlite_context": MagicMock(return_value="sqlite status"),
        "_pg_connection": MagicMock(return_value=("conn", None)),
        "_count_memories": MagicMock(return_value=3),
        "_pg_empty_store": MagicMock(return_value="empty status"),
        "_pg_banner": MagicMock(return_value="banner status"),
    }
    mocks.update(overrides)
    with ExitStack() as stack:
        for name, mock in mocks.items():
            stack.enter_context(patch.object(hook, name, mock))
        mocks["result"] = hook._session_start()
    return mocks


def test_the_event_and_project_root_reach_the_background_work():
    m = _run()
    m["harden_at_startup"].assert_called_once_with()
    m["_refresh_session_registry"].assert_called_once_with(EVENT)
    m["resolve_project_root"].assert_called_once_with(EVENT, os.environ)
    m["_auto_wire_pipeline"].assert_called_once_with(ROOT)
    m["_maybe_background_reanalyze"].assert_called_once_with(
        ROOT, hook._lookup_cached_graph_path
    )
    m["_maybe_background_prune_graphs"].assert_called_once_with()
    m["_maybe_background_consolidate"].assert_called_once_with()


def test_sqlite_receives_the_event_and_its_callbacks():
    m = _run(_backend_is_sqlite=MagicMock(return_value=True))
    m["_sqlite_context"].assert_called_once_with(
        EVENT, hook._auto_backfill, hook._emit_store_receipt
    )
    assert m["result"] == "sqlite status"
    m["_pg_connection"].assert_not_called()


def test_a_postgres_store_with_memories_gets_the_banner():
    m = _run()
    m["_count_memories"].assert_called_once_with("conn")
    m["_pg_banner"].assert_called_once_with(EVENT, "conn", 3)
    assert m["result"] == "banner status"
    m["_pg_empty_store"].assert_not_called()


def test_an_empty_postgres_store_gets_the_cold_start():
    m = _run(_count_memories=MagicMock(return_value=0))
    m["_pg_empty_store"].assert_called_once_with("conn")
    assert m["result"] == "empty status"
    m["_pg_banner"].assert_not_called()


def test_a_failed_connection_returns_its_status():
    m = _run(_pg_connection=MagicMock(return_value=(None, "not ready")))
    assert m["result"] == "not ready"
    m["_count_memories"].assert_not_called()
