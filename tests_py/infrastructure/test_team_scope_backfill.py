"""One-shot team-scope backfill for decisions stored before #561.

source: ADR-0200"""

from __future__ import annotations

import os
import tempfile

import pytest

from mcp_server.core import capture_origin
from mcp_server.infrastructure.team_scope_backfill import (
    TEAM_DECISION_BACKFILL_PG,
    TEAM_DECISION_BACKFILL_SQLITE,
)

# (label, row overrides, expected is_global after the backfill)
_CASES = [
    ("decision", {}, True),
    ("anchored", {"tags": ["_anchor"]}, False),
    ("no-agent", {"agent_context": ""}, False),
    ("unprotected", {"is_protected": False}, False),
    ("network", {"capture_origin": "network"}, False),
    ("legacy", {"capture_origin": "legacy"}, False),
]


def _row(label: str, overrides: dict) -> dict:
    data = {
        "content": f"Decision: backfill fixture {label}",
        "tags": [],
        "is_protected": True,
        "is_global": False,
        "agent_context": "cortex",
        "capture_origin": "deliberate",
    }
    data.update(overrides)
    return data


def _is_global(conn, memory_id: int) -> bool:
    row = conn.execute(
        "SELECT is_global FROM memories WHERE id = %s", (memory_id,)
    ).fetchone()
    return bool(row["is_global"])


def test_sql_origin_list_matches_the_write_path():
    """The SQL literal duplicates capture_origin's allow-list (infrastructure
    cannot import core); this keeps the two from drifting."""
    allowed = sorted(capture_origin._ORIGINS_ALLOWED_CONTENT_BYPASS)
    literal = ", ".join(f"'{o}'" for o in allowed)
    assert f"capture_origin IN ({literal})" in TEAM_DECISION_BACKFILL_PG
    assert f"capture_origin IN ({literal})" in TEAM_DECISION_BACKFILL_SQLITE


@pytest.fixture()
def sqlite_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


def test_sqlite_store_init_backfills_pre_fix_decisions(sqlite_path):
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore(sqlite_path)
    ids = {}
    for label, overrides, _ in _CASES:
        ids[label] = store.insert_memory(_row(label, overrides))
        # insert_memory may normalise these; pin the pre-fix state directly.
        store._conn.execute(
            "UPDATE memories SET is_global = 0, capture_origin = %s WHERE id = %s",
            (_row(label, overrides)["capture_origin"], ids[label]),
        )
    store._conn.commit()

    reopened = SqliteMemoryStore(sqlite_path)
    for label, _, expected in _CASES:
        assert _is_global(reopened._conn, ids[label]) is expected, label


def test_pg_backfill_statement():
    from mcp_server.handlers.forget import _get_store

    store = _get_store()
    if type(store).__name__ != "PgMemoryStore":
        pytest.skip("PostgreSQL backend not selected for this run")
    ids = {}
    for label, overrides, _ in _CASES:
        ids[label] = store.insert_memory(_row(label, overrides))
        store._conn.execute(
            "UPDATE memories SET is_global = FALSE, capture_origin = %s WHERE id = %s",
            (_row(label, overrides)["capture_origin"], ids[label]),
        )
    store._conn.execute(TEAM_DECISION_BACKFILL_PG)
    for label, _, expected in _CASES:
        assert _is_global(store._conn, ids[label]) is expected, label
