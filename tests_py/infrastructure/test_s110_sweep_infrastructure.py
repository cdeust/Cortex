"""S110 sweep (issue #197, first family): infrastructure try/except/pass sites.

Covers the ``silent_failure`` signals added to the sqlite store and wiki
store (including the README-clobber bug fix), the debug-log teardown
signals in pg_store / mcp_client / ap_bridge / groomer / AST source, and
the behaviour of the typed-narrowed handlers (hook cooldown caches,
install-lock release).
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

from mcp_server.observability import silent_failure
from tests_py.conftest import requires_psycopg  # type: ignore

WARN_LOGGER = "mcp_server.observability.silent_failure"


@pytest.fixture(autouse=True)
def _reset():
    silent_failure.reset()
    yield
    silent_failure.reset()


def _assert_noted(component: str, error_text: str) -> None:
    """Exact-component check via silent_failure.status().

    The caplog asserts pin that a WARNING was emitted; this pins the exact
    component name and that the real exception (not None) was recorded —
    the two mutants a substring-in-message assert lets survive
    (mutation run, scripts/mutation_check.sh, 2026-07-28).
    """
    status = silent_failure.status()
    assert component in status
    assert error_text in str(status[component]["last_error"])


class _VecPoisonConn:
    """Delegating connection proxy that raises on chosen SQL fragments."""

    def __init__(self, real, poison: str):
        self._real = real
        self._poison = poison

    def execute(self, sql, *args, **kwargs):
        if self._poison in sql:
            raise RuntimeError(f"poisoned: {self._poison}")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture()
def sqlite_store(tmp_path):
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore(str(tmp_path / "s110.db"))
    yield store
    store.close()


class TestSqliteVecIndexSignals:
    def test_reembed_vec_failure_is_logged(self, caplog, sqlite_store):
        emb = np.zeros(4, dtype=np.float32).tobytes()
        sqlite_store._has_vec = True
        sqlite_store._conn = _VecPoisonConn(sqlite_store._conn, "memories_vec")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            sqlite_store.reembed_memory(1, emb)
        assert any("sqlite_store.vec_index_update" in r.message for r in caplog.records)
        _assert_noted("sqlite_store.vec_index_update", "poisoned: memories_vec")

    def test_delete_memory_vec_failure_still_deletes_row(self, caplog, sqlite_store):
        memory_id = sqlite_store.insert_memory({"content": "doomed", "tags": []})
        sqlite_store._has_vec = True
        sqlite_store._conn = _VecPoisonConn(sqlite_store._conn, "memories_vec")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            assert sqlite_store.delete_memory(memory_id) is True
        assert sqlite_store.get_memory(memory_id) is None
        assert any("sqlite_store.vec_index_delete" in r.message for r in caplog.records)
        _assert_noted("sqlite_store.vec_index_delete", "poisoned: memories_vec")

    def test_delete_by_tag_vec_failure_still_purges(self, caplog, sqlite_store):
        memory_id = sqlite_store.insert_memory(
            {"content": "tagged", "tags": ["purge-me"]}
        )
        sqlite_store._conn = _VecPoisonConn(sqlite_store._conn, "memories_vec")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            deleted = sqlite_store.delete_memories_by_tag("purge-me")
        assert deleted == 1
        assert sqlite_store.get_memory(memory_id) is None
        assert any("sqlite_store.vec_index_delete" in r.message for r in caplog.records)
        _assert_noted("sqlite_store.vec_index_delete", "poisoned: memories_vec")

    def test_rrf_fts_signal_failure_degrades_and_is_logged(self, caplog, sqlite_store):
        scores: dict[int, float] = {}
        sqlite_store._conn = _VecPoisonConn(sqlite_store._conn, "memories_fts")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            sqlite_store._signal_fts(scores, "hello world", 1.0, 60, 10)
        assert scores == {}
        assert any("sqlite_store.rrf_fts_signal" in r.message for r in caplog.records)
        _assert_noted("sqlite_store.rrf_fts_signal", "poisoned: memories_fts")

    def test_rrf_vector_signal_failure_degrades_and_is_logged(
        self, caplog, sqlite_store
    ):
        scores: dict[int, float] = {}
        sqlite_store._has_vec = True
        sqlite_store._conn = _VecPoisonConn(sqlite_store._conn, "memories_vec")
        emb = np.zeros(4, dtype=np.float32).tobytes()
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            sqlite_store._signal_vector(scores, emb, 1.0, 60, 10)
        assert scores == {}
        assert any(
            "sqlite_store.rrf_vector_signal" in r.message for r in caplog.records
        )
        _assert_noted("sqlite_store.rrf_vector_signal", "poisoned: memories_vec")

    def test_pre_migration_value_write_is_still_a_noop(self, sqlite_store):
        import sqlite3

        class LegacyConn(_VecPoisonConn):
            def execute(self, sql, *args, **kwargs):
                if "SET value" in sql:
                    raise sqlite3.OperationalError("no such column: value")
                return self._real.execute(sql, *args, **kwargs)

        sqlite_store._conn = LegacyConn(sqlite_store._conn, "")
        sqlite_store.update_memory_value(1, 0.5)  # must not raise

    def test_pre_migration_extinction_write_is_still_a_noop(self, sqlite_store):
        import sqlite3

        class LegacyConn(_VecPoisonConn):
            def execute(self, sql, *args, **kwargs):
                if "SET extinction_strength" in sql:
                    raise sqlite3.OperationalError("no such column")
                return self._real.execute(sql, *args, **kwargs)

        sqlite_store._conn = LegacyConn(sqlite_store._conn, "")
        sqlite_store.update_memory_extinction(1, 0.5)  # must not raise

    def test_pre_migration_mood_write_is_still_a_noop(self, sqlite_store):
        import sqlite3

        class LegacyConn(_VecPoisonConn):
            def execute(self, sql, *args, **kwargs):
                if "user_mood" in sql:
                    raise sqlite3.OperationalError("no such table: user_mood")
                return self._real.execute(sql, *args, **kwargs)

        sqlite_store._conn = LegacyConn(sqlite_store._conn, "")
        sqlite_store.set_user_mood(0.1, 0.2)  # must not raise


class TestWikiStoreReadmeGuard:
    def test_unreadable_readme_is_not_clobbered(self, caplog, tmp_path):
        """Regression (this PR): an unreadable README used to fall through
        with should_write=True and get overwritten — data loss for a
        hand-written README the marker check could not inspect."""
        from mcp_server.infrastructure.wiki_store import _try_reindex

        readme = tmp_path / "README.md"
        garbage = b"\xff\xfe\x00 hand-written, not valid utf-8"
        readme.write_bytes(garbage)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            _try_reindex(tmp_path)
        assert readme.read_bytes() == garbage
        assert any("wiki_store.readme_read" in r.message for r in caplog.records)
        _assert_noted("wiki_store.readme_read", "utf-8")

    def test_auto_generated_readme_is_still_refreshed(self, tmp_path):
        from mcp_server.infrastructure.wiki_store import _try_reindex

        marker = "<!-- cortex-wiki-readme: auto-generated -->"
        readme = tmp_path / "README.md"
        readme.write_text(f"old body\n{marker}\n")
        _try_reindex(tmp_path)
        refreshed = readme.read_text()
        assert marker in refreshed
        assert "old body" not in refreshed

    def test_reindex_failure_is_logged(self, caplog, tmp_path, monkeypatch):
        from mcp_server.infrastructure import wiki_store
        from mcp_server.infrastructure.wiki_store import _try_reindex

        def broken(paths):
            raise RuntimeError("index builder broke")

        # Patch the consumer's own binding (top-level import, #197 family 4).
        monkeypatch.setattr(wiki_store, "build_index", broken)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            _try_reindex(tmp_path)
        assert any("wiki_store.reindex" in r.message for r in caplog.records)
        _assert_noted("wiki_store.reindex", "index builder broke")


@requires_psycopg
class TestPgStoreTeardownSignals:
    def test_pool_close_failures_are_logged_and_pools_cleared(self, caplog):
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        store = PgMemoryStore.__new__(PgMemoryStore)
        store._conn = MagicMock()
        store._interactive_pool = MagicMock()
        store._interactive_pool.close.side_effect = RuntimeError("pool wedged")
        store._batch_pool = MagicMock()
        store._batch_pool.close.side_effect = RuntimeError("pool wedged")
        with caplog.at_level("DEBUG", logger="mcp_server.infrastructure.pg_store"):
            store.close()
        assert store._interactive_pool is None
        assert store._batch_pool is None
        messages = [r.message for r in caplog.records]
        assert any("interactive pool close failed" in m for m in messages)
        assert any("batch pool close failed" in m for m in messages)

    def test_deallocate_failure_is_logged(self, caplog):
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        store = PgMemoryStore.__new__(PgMemoryStore)
        store._conn = MagicMock()
        store._conn.execute.side_effect = RuntimeError("connection lost")
        with caplog.at_level("DEBUG", logger="mcp_server.infrastructure.pg_store"):
            store._deallocate_all()
        assert any(
            "DEALLOCATE ALL after schema init failed" in r.message
            for r in caplog.records
        )


class TestMcpClientTeardown:
    def test_close_survives_proc_failures_and_logs_debug(self, caplog):
        from mcp_server.infrastructure.mcp_client import MCPClient

        client = MCPClient({"command": "true"})
        proc = MagicMock()
        proc.stdin.close.side_effect = RuntimeError("pipe broken")
        proc.terminate.side_effect = ProcessLookupError()
        client._proc = proc
        with caplog.at_level("DEBUG", logger="mcp_server.infrastructure.mcp_client"):
            client.close()
        assert client._proc is None
        messages = [r.message for r in caplog.records]
        assert any("stdin close failed" in m for m in messages)
        assert any("terminate failed" in m for m in messages)

    def test_touch_activity_without_running_loop_is_a_noop(self):
        from mcp_server.infrastructure.mcp_client import MCPClient

        client = MCPClient({"command": "true"})
        client._touch_activity()  # no running loop — must not raise


class TestApBridgeTeardown:
    def test_close_survives_client_failure_and_logs_debug(self, caplog):
        from mcp_server.infrastructure.ap_bridge import APBridge

        bridge = APBridge.__new__(APBridge)
        bridge._client = MagicMock()
        bridge._client.close.side_effect = RuntimeError("already dead")
        with caplog.at_level("DEBUG", logger="mcp_server.infrastructure.ap_bridge"):
            asyncio.run(bridge.close())
        assert bridge._client is None
        assert any("AP client close failed" in r.message for r in caplog.records)


class TestSyncLoopTeardown:
    def test_close_survives_runtime_errors(self):
        from mcp_server.infrastructure.workflow_graph_source_ast import _SyncLoop

        owner = _SyncLoop.__new__(_SyncLoop)
        loop = MagicMock()
        loop.is_closed.return_value = False
        loop.call_soon_threadsafe.side_effect = RuntimeError("loop closed")
        loop.close.side_effect = RuntimeError("loop running")
        owner._loop = loop
        owner._thread = None
        owner.close()  # must not raise
        assert owner._loop is None


class TestGroomerStopCallback:
    def test_stop_fn_failure_is_logged_and_stop_still_fires(
        self, caplog, tmp_path, monkeypatch
    ):
        from mcp_server.infrastructure.groomer_coordinator import GroomerCoordinator

        coordinator = GroomerCoordinator.__new__(GroomerCoordinator)
        coordinator.pid_path = tmp_path / "groomer.pid"
        monkeypatch.setattr(coordinator, "deregister", lambda pid: None)
        monkeypatch.setattr(coordinator, "live_session_count", lambda: 0)
        monkeypatch.setattr(coordinator, "_log_run", lambda *a, **k: None)

        def broken_stop():
            raise RuntimeError("groomer wedged")

        with caplog.at_level(
            "DEBUG", logger="mcp_server.infrastructure.groomer_coordinator"
        ):
            assert coordinator.stop_if_last(123, stop_fn=broken_stop) is True
        assert any("groomer stop callback failed" in r.message for r in caplog.records)


class TestHookCooldownCaches:
    @pytest.mark.parametrize(
        "module_name",
        [
            "mcp_server.hooks.pipeline_impact_bump",
            "mcp_server.hooks.preemptive_context",
            "mcp_server.hooks.post_commit_reindex",
        ],
    )
    def test_corrupt_cooldown_file_means_no_cooldown(
        self, module_name, tmp_path, monkeypatch
    ):
        import importlib

        module = importlib.import_module(module_name)
        corrupt = tmp_path / "cooldown.json"
        corrupt.write_text("{ not json")
        monkeypatch.setattr(module, "_COOLDOWN_FILE", corrupt)
        assert module._check_cooldown("some-key") is False

    @pytest.mark.parametrize(
        "module_name",
        [
            "mcp_server.hooks.pipeline_impact_bump",
            "mcp_server.hooks.preemptive_context",
            "mcp_server.hooks.post_commit_reindex",
        ],
    )
    def test_corrupt_timestamp_type_means_no_cooldown(
        self, module_name, tmp_path, monkeypatch
    ):
        import importlib
        import json

        module = importlib.import_module(module_name)
        cooldown = tmp_path / "cooldown.json"
        cooldown.write_text(json.dumps({"some-key": "yesterday"}))
        monkeypatch.setattr(module, "_COOLDOWN_FILE", cooldown)
        assert module._check_cooldown("some-key") is False

    @pytest.mark.parametrize(
        "module_name",
        [
            "mcp_server.hooks.pipeline_impact_bump",
            "mcp_server.hooks.preemptive_context",
            "mcp_server.hooks.post_commit_reindex",
        ],
    )
    def test_unwritable_cooldown_dir_does_not_raise(
        self, module_name, tmp_path, monkeypatch
    ):
        import importlib

        module = importlib.import_module(module_name)
        missing_dir = tmp_path / "no-such-dir" / "cooldown.json"
        monkeypatch.setattr(module, "_COOLDOWN_FILE", missing_dir)
        module._update_cooldown("some-key")  # must not raise


@pytest.mark.skipif(sys.platform == "win32", reason="posix flock variant")
class TestInstallLockRelease:
    def test_release_on_closed_fd_is_swallowed(self, tmp_path):
        from mcp_server.infrastructure import pipeline_install_lock as lock_mod

        fd = os.open(str(tmp_path / "lockfile"), os.O_RDWR | os.O_CREAT)
        os.close(fd)
        lock_mod._release(fd)  # closed fd raises OSError internally — swallowed


class TestSessionStartPgClose:
    def test_close_failure_is_reported_to_stderr(self, capsys, monkeypatch):
        from mcp_server.hooks import session_start

        conn = MagicMock()
        conn.execute.side_effect = RuntimeError("query broke")
        conn.close.side_effect = ValueError("close broke")
        monkeypatch.setattr(session_start, "_connect_pg", lambda: conn)
        assert session_start._lookup_cached_graph_path("/some/project") is None
        err = capsys.readouterr().err
        assert "pg connection close failed" in err


@requires_psycopg
class TestPgStoreRecoverySignals:
    def test_reconnect_survives_failed_close_and_logs_debug(self, caplog, monkeypatch):
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        store = PgMemoryStore.__new__(PgMemoryStore)
        old_conn = MagicMock()
        old_conn.close.side_effect = RuntimeError("already broken")
        store._conn = old_conn
        fresh = MagicMock()
        monkeypatch.setattr(store, "_create_connection", lambda: fresh)
        # register_vector needs a real psycopg connection; the reconnect
        # contract under test is the close-failure handling, not pgvector.
        # _reconnect lives in pg_store_schema.py (split out of pg_store.py,
        # over the 300-line §4.1 cap) — patch register_vector where it is
        # actually called from, not the pg_store.py facade.
        from mcp_server.infrastructure import pg_store_schema as pg_store_schema_mod

        monkeypatch.setattr(pg_store_schema_mod, "register_vector", lambda conn: None)
        with caplog.at_level("DEBUG", logger="mcp_server.infrastructure.pg_store"):
            store._reconnect()
        assert store._conn is fresh
        assert any(
            "close of stale connection failed during reconnect" in r.message
            for r in caplog.records
        )

    def test_stale_plan_recovery_survives_failed_rollback_and_deallocate(self, caplog):
        import psycopg

        from mcp_server.infrastructure.pg_store import PgMemoryStore

        store = PgMemoryStore.__new__(PgMemoryStore)
        conn = MagicMock()
        result_cursor = MagicMock()
        result_cursor.rowcount = 0
        result_cursor.fetchall.return_value = []
        stale = psycopg.errors.FeatureNotSupported()

        def execute(sql, *args, **kwargs):
            if sql == "DEALLOCATE ALL":
                raise RuntimeError("deallocate broke")
            if conn.execute.call_count == 1:
                raise stale
            return result_cursor

        conn.execute.side_effect = execute
        conn.rollback.side_effect = RuntimeError("rollback broke")
        with caplog.at_level("DEBUG", logger="mcp_server.infrastructure.pg_store"):
            store._execute_on_conn(conn, "SELECT 1", None)
        messages = [r.message for r in caplog.records]
        assert any("rollback during stale-plan recovery failed" in m for m in messages)
        assert any(
            "DEALLOCATE ALL during stale-plan recovery failed" in m for m in messages
        )


class TestMcpClientStderrPump:
    def test_pump_death_is_logged_debug(self, caplog, monkeypatch):
        from mcp_server.infrastructure.mcp_client import MCPClient

        client = MCPClient({"command": "true"})
        monkeypatch.setattr(client, "_open_stderr_log", lambda: None)
        proc = MagicMock()
        proc.stderr.readline.side_effect = RuntimeError("stream corrupted")
        client._proc = proc
        with caplog.at_level("DEBUG", logger="mcp_server.infrastructure.mcp_client"):
            asyncio.run(client._stderr_loop())
        assert any("stderr pump terminated" in r.message for r in caplog.records)

    def test_unwritable_mirror_log_keeps_pumping(self, capsys, monkeypatch):
        from mcp_server.infrastructure.mcp_client import MCPClient

        client = MCPClient({"command": "true"})
        log_fh = MagicMock()
        log_fh.write.side_effect = OSError("disk full")
        log_fh.close.side_effect = OSError("also broken")
        monkeypatch.setattr(client, "_open_stderr_log", lambda: log_fh)

        lines = [b"upstream says hi\n", b""]

        async def readline():
            return lines.pop(0)

        proc = MagicMock()
        proc.stderr.readline = readline
        client._proc = proc
        asyncio.run(client._stderr_loop())  # must not raise
        assert "upstream says hi" in capsys.readouterr().err


class TestWorkflowAstSourceClose:
    def test_bridge_close_failure_is_logged_and_loop_still_closed(self, caplog):
        from mcp_server.infrastructure.workflow_graph_source_ast import (
            WorkflowGraphASTSource,
        )

        source = WorkflowGraphASTSource.__new__(WorkflowGraphASTSource)
        source._bridge = MagicMock()
        source._bridge.close.return_value = None
        owner = MagicMock()
        owner.run.side_effect = RuntimeError("loop wedged")
        source._loop_owner = owner
        with caplog.at_level(
            "DEBUG", logger="mcp_server.infrastructure.workflow_graph_source_ast"
        ):
            source.close()
        owner.close.assert_called_once()
        assert any(
            "AP bridge close failed during teardown" in r.message
            for r in caplog.records
        )

    def test_sync_loop_join_runtimeerror_is_swallowed(self):
        from mcp_server.infrastructure import workflow_graph_source_ast as mod
        from mcp_server.infrastructure.workflow_graph_source_ast import _SyncLoop

        owner = _SyncLoop.__new__(_SyncLoop)
        loop = MagicMock()
        loop.is_closed.return_value = False
        thread = MagicMock()
        thread.join.side_effect = RuntimeError("cannot join current thread")
        owner._loop = loop
        owner._thread = thread
        owner.close()  # must not raise
        assert owner._loop is None
        # The shutdown-drain ceiling is a single named constant shared by
        # the thread-join bound and _drain_pending_tasks's own wait —
        # pins the actual value passed, not just "some timeout".
        thread.join.assert_called_once_with(timeout=mod._SHUTDOWN_DRAIN_TIMEOUT_S)
