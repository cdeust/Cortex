"""The deterministic benchmark session keeps the store's iterative HNSW scan.

``apply_deterministic_session`` starts with ``DISCARD ALL``, which resets
every session setting, ``hnsw.iterative_scan`` included; before ADR-1105's
follow-up an ablation run left the connection on the lossy ``off`` path.
Live PG (throwaway test database via conftest); skipped on SQLite.

source: ADR-1105
"""

from __future__ import annotations

import os

import pytest

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store

# source: ADR-1112 (tests of the store itself run on the in-process store)
pytestmark = pytest.mark.in_process_store


@pytest.fixture
def pg_url():
    settings = get_memory_settings()
    shared = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    if not hasattr(shared, "batch_pool"):
        pytest.skip("hnsw.iterative_scan is PostgreSQL-only")
    return os.environ["DATABASE_URL"]


@pytest.mark.parametrize("autocommit", [True, False])
def test_session_scans_iteratively_after_discard_all(pg_url, autocommit):
    import psycopg  # noqa: PLC0415 — PG-only import

    from benchmarks.lib import db_setup  # noqa: PLC0415 — hard-imports psycopg

    with psycopg.connect(pg_url, autocommit=autocommit) as conn:
        db_setup.apply_deterministic_session(conn, run_id="iterscan")
        conn.execute("SELECT '[1]'::vector")  # defines hnsw.* in this backend
        live = conn.execute("SHOW hnsw.iterative_scan").fetchone()
    assert live is not None
    assert live[0] == "relaxed_order"
