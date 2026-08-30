"""HC-CORTEX-002 request-boundary transaction ownership regressions."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.infrastructure import sqlite_connection_registry as registry_module
from mcp_server.infrastructure.sqlite_request_scope import (
    UncommittedSqliteTransactionError,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.tool_error_handler import _run_coroutine_on_thread, safe_handler

# source: repository worker teardown convention in
# tests_py/infrastructure/test_workflow_graph_source_ast.py.
_THREAD_SAFETY_BOUND_SECONDS = 5


def test_success_cannot_acknowledge_uncommitted_work(tmp_path: Path) -> None:
    store = SqliteMemoryStore(str(tmp_path / "unfinished-request.sqlite3"))

    async def unfinished_request(_args: dict) -> dict:
        store._conn.execute(
            "INSERT INTO entities (name, type) VALUES (?, ?)",
            ("uncommitted", "test"),
        )
        return {"acknowledged": True}

    with pytest.raises(UncommittedSqliteTransactionError, match="uncommitted"):
        _run_coroutine_on_thread(unfinished_request, {})
    count = store._conn.execute(
        "SELECT COUNT(*) AS count FROM entities WHERE name = ?", ("uncommitted",)
    ).fetchone()["count"]
    assert count == 0
    store.close()


def test_request_tracks_transaction_opened_by_nested_worker(tmp_path: Path) -> None:
    store = SqliteMemoryStore(str(tmp_path / "nested-worker.sqlite3"))

    async def nested_worker_request(_args: dict) -> dict:
        await asyncio.to_thread(
            store._conn.execute,
            "INSERT INTO memories (content) VALUES (?)",
            ("nested-worker-uncommitted",),
        )
        return {"acknowledged": True}

    with pytest.raises(UncommittedSqliteTransactionError, match="uncommitted"):
        _run_coroutine_on_thread(nested_worker_request, {})
    count = store._conn.execute(
        "SELECT COUNT(*) AS count FROM memories WHERE content = ?",
        ("nested-worker-uncommitted",),
    ).fetchone()["count"]
    assert count == 0
    store.close()


def test_request_releases_connection_owned_by_nested_worker(tmp_path: Path) -> None:
    store = SqliteMemoryStore(str(tmp_path / "nested-worker-lifecycle.sqlite3"))
    initial_connections = len(store._connection_registry._connections)

    async def nested_worker_request(args: dict) -> dict:
        entity_id = await asyncio.to_thread(
            store.insert_entity,
            {"name": args["name"], "type": "test"},
        )
        return {"entity_id": entity_id}

    try:
        for name in ("first-request", "second-request"):
            result = _run_coroutine_on_thread(nested_worker_request, {"name": name})
            assert result["entity_id"] > 0
            assert len(store._connection_registry._connections) == initial_connections
    finally:
        store.close()


def test_safe_handler_releases_connection_from_ephemeral_outer_executor(
    tmp_path: Path,
) -> None:
    store = SqliteMemoryStore(str(tmp_path / "outer-worker-lifecycle.sqlite3"))
    initial_connections = len(store._connection_registry._connections)

    async def direct_request(args: dict) -> dict:
        entity_id = store.insert_entity({"name": args["name"], "type": "test"})
        return {"entity_id": entity_id}

    try:
        for name in ("first-request", "second-request"):
            result = asyncio.run(safe_handler(direct_request, {"name": name}))
            assert result["entity_id"] > 0
            assert len(store._connection_registry._connections) == initial_connections
    finally:
        store.close()


def test_nested_safe_handler_is_rejected_before_inner_work(tmp_path: Path) -> None:
    store = SqliteMemoryStore(str(tmp_path / "nested-handler.sqlite3"))
    inner_entered: list[bool] = []

    async def rejected_inner(_args: dict) -> dict:
        inner_entered.append(True)
        store._conn.execute(
            "INSERT INTO memories (content) VALUES (?)", ("rejected-inner",)
        )
        raise RuntimeError("inner rejected")

    async def outer(_args: dict) -> dict:
        with pytest.raises(ToolError):
            await safe_handler(rejected_inner, {})
        entity_id = store.insert_entity({"name": "ack-outer", "type": "test"})
        return {"entity_id": entity_id}

    result = asyncio.run(safe_handler(outer, {}))
    assert result["entity_id"] > 0
    assert inner_entered == []
    count = store._conn.execute(
        "SELECT COUNT(*) AS count FROM memories WHERE content = ?",
        ("rejected-inner",),
    ).fetchone()["count"]
    assert count == 0
    store.close()


def test_concurrent_unadmitted_handlers_do_not_share_transaction(
    tmp_path: Path,
) -> None:
    store = SqliteMemoryStore(str(tmp_path / "unadmitted-concurrency.sqlite3"))
    rejected_written = threading.Event()
    acknowledged_attempting = threading.Event()

    async def rejected(_args: dict) -> dict:
        store._conn.execute(
            "INSERT INTO memories (content) VALUES (?)", ("rejected-inline",)
        )
        rejected_written.set()
        assert await asyncio.to_thread(
            acknowledged_attempting.wait, _THREAD_SAFETY_BOUND_SECONDS
        )
        raise RuntimeError("reject during concurrent request")

    async def acknowledged(_args: dict) -> dict:
        assert await asyncio.to_thread(
            rejected_written.wait, _THREAD_SAFETY_BOUND_SECONDS
        )
        acknowledged_attempting.set()
        entity_id = store.insert_entity({"name": "ack-inline", "type": "test"})
        return {"entity_id": entity_id}

    async def run_both() -> list[object]:
        return await asyncio.gather(
            safe_handler(rejected, {}),
            safe_handler(acknowledged, {}),
            return_exceptions=True,
        )

    results = asyncio.run(run_both())
    assert isinstance(results[0], ToolError)
    assert isinstance(results[1], dict)
    count = store._conn.execute(
        "SELECT COUNT(*) AS count FROM memories WHERE content = ?",
        ("rejected-inline",),
    ).fetchone()["count"]
    assert count == 0
    store.close()


def test_rollback_failure_quarantines_dirty_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "rollback-quarantine.sqlite3"
    store = SqliteMemoryStore(str(db_path))

    def fail_rollback(_connection: object) -> None:
        raise RuntimeError("injected rollback failure")

    async def rejected(_args: dict) -> dict:
        store._conn.execute(
            "INSERT INTO memories (content) VALUES (?)", ("rejected-cleanup",)
        )
        raise ValueError("original handler failure")

    async def acknowledged(_args: dict) -> dict:
        entity_id = store.insert_entity({"name": "ack-next", "type": "test"})
        return {"entity_id": entity_id}

    monkeypatch.setattr(registry_module, "_rollback_native", fail_rollback)
    with pytest.raises(ValueError, match="original handler failure"):
        _run_coroutine_on_thread(rejected, {})
    result = _run_coroutine_on_thread(acknowledged, {})
    assert result["entity_id"] > 0
    store.close()

    reopened = SqliteMemoryStore(str(db_path))
    rejected_count = reopened._conn.execute(
        "SELECT COUNT(*) AS count FROM memories WHERE content = ?",
        ("rejected-cleanup",),
    ).fetchone()["count"]
    acknowledged_count = reopened._conn.execute(
        "SELECT COUNT(*) AS count FROM entities WHERE name = ?", ("ack-next",)
    ).fetchone()["count"]
    assert rejected_count == 0
    assert acknowledged_count == 1
    reopened.close()


def test_in_memory_anchor_rollback_failure_invalidates_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqliteMemoryStore()

    def fail_rollback(_connection: object) -> None:
        raise RuntimeError("injected anchor rollback failure")

    async def rejected(_args: dict) -> dict:
        store._conn.execute(
            "INSERT INTO memories (content) VALUES (?)", ("rejected-anchor",)
        )
        raise ValueError("original in-memory handler failure")

    monkeypatch.setattr(registry_module, "_rollback_native", fail_rollback)
    with pytest.raises(ValueError, match="original in-memory handler failure"):
        _run_coroutine_on_thread(rejected, {})
    with pytest.raises(sqlite3.ProgrammingError, match="anchor rollback failed"):
        store._conn.execute("SELECT COUNT(*) FROM memories")
    store.close()
