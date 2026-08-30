"""HC-CORTEX-002: a worker owns its complete SQLite transaction.

The fault fixture is the smallest baseline reproduction from ADR-0055. A
supersede is rejected after its insert and compare-and-set while an unrelated
insert attempts to commit. The external ledger, not SQLite's physical
integrity result, decides which rows are allowed to survive.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.tool_error_handler import _run_coroutine_on_thread

# source: repository worker teardown convention in
# tests_py/infrastructure/test_workflow_graph_source_ast.py.
_THREAD_SAFETY_BOUND_SECONDS = 5


class InjectedRollbackError(RuntimeError):
    """Fault after the supersede CAS but before its commit."""


def _memory(content: str) -> dict[str, object]:
    embedding = np.zeros(384, dtype=np.float32).tobytes()
    return {
        "content": content,
        "domain": "hc-cortex-002",
        "embedding": embedding,
        "heat": 0.5,
    }


@dataclass
class OperationLedger:
    acknowledged_ids: list[int] = field(default_factory=list)
    rejected_operations: list[str] = field(default_factory=list)
    busy_retries: int = 0
    errors: list[str] = field(default_factory=list)


class ConcurrentFaultFixture:
    def __init__(self, store: SqliteMemoryStore, target_id: int) -> None:
        self.store = store
        self.target_id = target_id
        self.ledger = OperationLedger()
        self.writer_ready = threading.Event()
        self.fault_window_open = threading.Event()
        self.first_write_finished = threading.Event()
        self.rollback_finished = threading.Event()

    def run(self) -> OperationLedger:
        original_transfer = self.store._transfer_anchor
        self.store._transfer_anchor = self._inject_after_cas  # type: ignore[method-assign]
        writer = threading.Thread(target=self._run_insert)
        superseder = threading.Thread(target=self._run_supersede)
        try:
            writer.start()
            self._wait(self.writer_ready, "writer connection was not ready")
            superseder.start()
            superseder.join(timeout=_THREAD_SAFETY_BOUND_SECONDS)
            writer.join(timeout=_THREAD_SAFETY_BOUND_SECONDS)
            assert not superseder.is_alive() and not writer.is_alive()
            return self.ledger
        finally:
            self.store._transfer_anchor = original_transfer  # type: ignore[method-assign]

    def _inject_after_cas(self, _head_id: int, _new_id: int) -> None:
        self.fault_window_open.set()
        self._wait(self.first_write_finished, "concurrent write never finished")
        raise InjectedRollbackError("fault after supersede compare-and-set")

    def _run_supersede(self) -> None:
        try:
            self.store.supersede_atomic(_memory("rejected-supersede"), self.target_id)
        except InjectedRollbackError:
            self.ledger.rejected_operations.append("rejected-supersede")
        except Exception as exc:  # pragma: no cover - diagnostic boundary
            self._record_error("supersede", exc)
        finally:
            self.rollback_finished.set()

    def _run_insert(self) -> None:
        self.store._raw_conn.execute("PRAGMA busy_timeout=0")
        self.writer_ready.set()
        self._wait(self.fault_window_open, "fault window never opened")
        try:
            self._insert_acknowledged()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                self._record_error("insert", exc)
            else:
                self.ledger.busy_retries += 1
            self.first_write_finished.set()
            self._wait(self.rollback_finished, "fault rollback never finished")
            self._retry_after_rollback()
        else:
            self.first_write_finished.set()

    def _retry_after_rollback(self) -> None:
        try:
            self._insert_acknowledged()
        except Exception as exc:  # pragma: no cover - diagnostic boundary
            self._record_error("insert-retry", exc)

    def _insert_acknowledged(self) -> None:
        memory_id = self.store.insert_memory(_memory("acknowledged-insert"))
        self.ledger.acknowledged_ids.append(memory_id)

    def _record_error(self, operation: str, exc: Exception) -> None:
        self.ledger.errors.append(f"{operation}:{type(exc).__name__}:{exc}")

    @staticmethod
    def _wait(event: threading.Event, message: str) -> None:
        assert event.wait(timeout=_THREAD_SAFETY_BOUND_SECONDS), message


def _snapshot(
    store: SqliteMemoryStore,
) -> tuple[list[dict], list[dict], list[int] | None]:
    rows = store._conn.execute(
        "SELECT id, content, superseded_by_id FROM memories ORDER BY id"
    ).fetchall()
    fts_rows = store._conn.execute(
        "SELECT rowid, content FROM memories_fts ORDER BY rowid"
    ).fetchall()
    vec_ids = None
    if store.has_vec:
        vec_ids = [
            row["rowid"]
            for row in store._conn.execute(
                "SELECT rowid FROM memories_vec ORDER BY rowid"
            ).fetchall()
        ]
    return rows, fts_rows, vec_ids


def _assert_ledger_matches_store(
    ledger: OperationLedger,
    target_id: int,
    rows: list[dict],
    fts_rows: list[dict],
    vec_ids: list[int] | None,
) -> None:
    contents = [row["content"] for row in rows]
    fts_contents = [row["content"] for row in fts_rows]
    target = next(row for row in rows if row["id"] == target_id)
    assert ledger.rejected_operations == ["rejected-supersede"]
    assert len(ledger.acknowledged_ids) == 1
    assert ledger.busy_retries == 1
    assert ledger.errors == []
    assert contents == ["target", "acknowledged-insert"]
    assert fts_contents == ["target", "acknowledged-insert"]
    assert target["superseded_by_id"] is None
    if vec_ids is not None:
        assert vec_ids == [target_id, ledger.acknowledged_ids[0]]


def test_rejected_transaction_cannot_be_committed_by_another_worker(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "transaction-isolation.sqlite3"
    store = SqliteMemoryStore(str(db_path))
    had_vec = store.has_vec
    target_id = store.insert_memory(_memory("target"))

    ledger = ConcurrentFaultFixture(store, target_id).run()
    rows, fts_rows, vec_ids = _snapshot(store)
    _assert_ledger_matches_store(ledger, target_id, rows, fts_rows, vec_ids)
    assert store._conn.execute("PRAGMA integrity_check").fetchone() == {
        "integrity_check": "ok"
    }
    assert store._conn.execute("PRAGMA foreign_key_check").fetchall() == []
    store.close()

    reopened = SqliteMemoryStore(str(db_path))
    assert reopened.has_vec is had_vec
    persisted_rows, persisted_fts, persisted_vec = _snapshot(reopened)
    _assert_ledger_matches_store(
        ledger, target_id, persisted_rows, persisted_fts, persisted_vec
    )
    reopened.close()


def test_in_memory_workers_keep_transaction_ownership() -> None:
    store = SqliteMemoryStore()
    target_id = store.insert_memory(_memory("target"))

    ledger = ConcurrentFaultFixture(store, target_id).run()
    rows, fts_rows, vec_ids = _snapshot(store)
    _assert_ledger_matches_store(ledger, target_id, rows, fts_rows, vec_ids)
    store.close()


def test_failed_request_cannot_leak_into_reused_worker(tmp_path: Path) -> None:
    db_path = tmp_path / "request-boundary.sqlite3"
    store = SqliteMemoryStore(str(db_path))
    store._conn.execute("DROP TABLE memories_fts")
    store._conn.commit()

    async def rejected_request(_args: dict) -> dict:
        store.insert_memory(_memory("rejected-partial"))
        return {"acknowledged": True}

    async def acknowledged_request(_args: dict) -> dict:
        entity_id = store.insert_entity({"name": "acknowledged", "type": "test"})
        return {"entity_id": entity_id}

    with pytest.raises(sqlite3.OperationalError, match="memories_fts"):
        _run_coroutine_on_thread(rejected_request, {})
    result = _run_coroutine_on_thread(acknowledged_request, {})
    assert result["entity_id"] > 0
    store.close()

    reopened = SqliteMemoryStore(str(db_path))
    rejected_count = reopened._conn.execute(
        "SELECT COUNT(*) AS count FROM memories WHERE content = ?",
        ("rejected-partial",),
    ).fetchone()["count"]
    acknowledged_count = reopened._conn.execute(
        "SELECT COUNT(*) AS count FROM entities WHERE name = ?",
        ("acknowledged",),
    ).fetchone()["count"]
    assert rejected_count == 0
    assert acknowledged_count == 1
    reopened.close()
