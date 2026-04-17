"""Phase 5 pool smoke tests.

Asserts:
    - interactive_pool / batch_pool lazily open on first access
    - acquire_interactive / acquire_batch yield usable connections
    - close() tears down both pools
    - POOL_DISABLED falls back to the persistent _conn

Source: docs/program/phase-5-pool-admission-design.md §1.1.
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.pg_store import PgMemoryStore


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    s.close()


class TestPoolLifecycle:
    def test_interactive_pool_lazy(self, store):
        """Pool is None until first property access."""
        assert store._interactive_pool is None
        pool = store.interactive_pool
        assert pool is not None
        assert store._interactive_pool is pool

    def test_batch_pool_lazy(self, store):
        assert store._batch_pool is None
        pool = store.batch_pool
        assert pool is not None
        assert store._batch_pool is pool

    def test_pools_are_distinct(self, store):
        assert store.interactive_pool is not store.batch_pool

    def test_acquire_interactive_yields_usable_connection(self, store):
        with store.acquire_interactive() as conn:
            row = conn.execute("SELECT 1 AS v").fetchone()
            assert row["v"] == 1

    def test_acquire_batch_yields_usable_connection(self, store):
        with store.acquire_batch() as conn:
            row = conn.execute("SELECT 2 AS v").fetchone()
            assert row["v"] == 2

    def test_pool_connection_registers_vector(self, store):
        """The configure callback must register the pgvector adapter so
        downstream code can bind vector parameters without extra work."""
        with store.acquire_interactive() as conn:
            # register_vector idempotent; smoke test by executing a
            # vector-returning query (pgvector installs the `vector` type).
            conn.execute("SELECT '[1,2,3]'::vector AS v").fetchone()


class TestPoolConfiguration:
    def test_interactive_pool_respects_settings(self, store):
        from mcp_server.infrastructure.memory_config import get_memory_settings

        settings = get_memory_settings()
        pool = store.interactive_pool
        assert pool.min_size == settings.POOL_INTERACTIVE_MIN
        assert pool.max_size == settings.POOL_INTERACTIVE_MAX

    def test_batch_pool_respects_settings(self, store):
        from mcp_server.infrastructure.memory_config import get_memory_settings

        settings = get_memory_settings()
        pool = store.batch_pool
        assert pool.min_size == settings.POOL_BATCH_MIN
        assert pool.max_size == settings.POOL_BATCH_MAX


class TestKillSwitch:
    def test_pool_disabled_yields_conn(self, store, monkeypatch):
        """When POOL_DISABLED=true, acquire_* yields the persistent _conn."""
        from mcp_server.infrastructure import memory_config

        settings = memory_config.get_memory_settings()
        monkeypatch.setattr(settings, "POOL_DISABLED", True, raising=False)

        with store.acquire_interactive() as conn:
            assert conn is store._conn

        with store.acquire_batch() as conn:
            assert conn is store._conn


class TestPoolTeardown:
    def test_close_tears_down_pools(self):
        """close() must close both pools and null the references."""
        s = PgMemoryStore()
        # Force lazy open of both
        _ = s.interactive_pool
        _ = s.batch_pool
        assert s._interactive_pool is not None
        assert s._batch_pool is not None
        s.close()
        assert s._interactive_pool is None
        assert s._batch_pool is None
