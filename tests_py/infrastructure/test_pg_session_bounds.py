"""The audit's probe A on the store's own connections (ADR-1112 increment 4;
docs/audits/2026-10-21-three-pillar-audit.md, E10 and Track 0.2): every
connection names itself and carries statement, lock and idle-transaction
bounds; background work runs on the batch pool.

On main every one of these settings was 0 or empty (E10). Records its
numbers through ``CORTEX_REPRO_JSON``
(``python scripts/repro_connection_broker.py bounds``).

source: ADR-1112
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests_py.conftest import _USE_PG

pytestmark = pytest.mark.skipif(not _USE_PG, reason="requires isolated PostgreSQL")

_SETTINGS = (
    "application_name",
    "statement_timeout",
    "lock_timeout",
    "idle_in_transaction_session_timeout",
)


def _show(conn) -> dict[str, str]:
    return {
        name: conn.execute("SELECT current_setting(%s) AS v", (name,)).fetchone()["v"]
        for name in _SETTINGS
    }


@pytest.fixture
def store():
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — PG-only import

    opened = PgMemoryStore(database_url=os.environ["DATABASE_URL"])
    yield opened
    opened.close()


def test_every_store_connection_is_named_and_bounded(store):
    with store.acquire_interactive() as conn:
        interactive = _show(conn)
    with store.acquire_batch() as conn:
        batch = _show(conn)
    direct = _show(store._conn)  # noqa: SLF001 — the persistent connection
    measured = {"interactive": interactive, "batch": batch, "direct": direct}
    target = os.environ.get("CORTEX_REPRO_JSON")
    if target:
        Path(target).write_text(json.dumps(measured))
    assert interactive == {
        "application_name": f"cortex-store-interactive-{os.getpid()}",
        "statement_timeout": "30s",
        "lock_timeout": "30s",
        "idle_in_transaction_session_timeout": "30s",
    }
    assert batch == {
        "application_name": f"cortex-store-batch-{os.getpid()}",
        "statement_timeout": "30min",
        "lock_timeout": "30min",
        "idle_in_transaction_session_timeout": "30s",
    }
    assert direct["application_name"] == f"cortex-store-direct-{os.getpid()}"
    assert direct["idle_in_transaction_session_timeout"] == "30s"


def test_background_work_runs_on_the_batch_pool(store):
    from mcp_server.infrastructure.store_operations import request_class  # noqa: PLC0415

    sql = "SELECT current_setting('application_name') AS v"
    assert store._execute(sql).fetchone()["v"].startswith("cortex-store-interactive-")  # noqa: SLF001
    with request_class("background"):
        assert store._execute(sql).fetchone()["v"].startswith("cortex-store-batch-")  # noqa: SLF001


def test_the_migration_connection_is_named_for_its_process(monkeypatch):
    """The broker's start-up migration is a connection of its own; named, a
    census attributes it to the broker (A2) instead of an unknown client."""
    from mcp_server.infrastructure import pg_migrations  # noqa: PLC0415 — PG-only import

    seen = []

    def record(conn):
        row = conn.execute("SELECT current_setting('application_name')").fetchone()
        seen.append(row[0])
        return 0

    monkeypatch.setattr(pg_migrations, "migrate_locked", record)
    pg_migrations.apply_schema(os.environ["DATABASE_URL"])
    assert seen == [f"cortex-migrate-{os.getpid()}"]
