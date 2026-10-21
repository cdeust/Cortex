"""Read-only PostgreSQL fixtures verify grooming timestamps after prefiltering.

source: docs/verification/codex-session-start-query-20261002.md
The fixtures use VALUES inside SELECT; no schema or stored rows are changed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from unittest.mock import Mock

import pytest


def _grooming_sql() -> str:
    from mcp_server.infrastructure.hook_queries import _GROOMING_AGES_SQL

    return _GROOMING_AGES_SQL


@pytest.mark.skipif(
    os.environ.get("CORTEX_MEMORY_STORE_BACKEND", "").strip().lower() == "sqlite",
    reason="PostgreSQL SQL fixtures do not apply to the explicit SQLite backend",
)
@pytest.mark.parametrize(
    ("rows", "distill_day", "promo_day"),
    [
        ([(None, [])], None, None),
        (
            [
                ("2026-01-01", ["lesson", "distill-of:a"]),
                ("2026-01-02", ["lesson", "promoted:a"]),
                ("2026-01-03", ["distill-of:b", "promoted:b"]),
            ],
            1,
            2,
        ),
        (
            [
                ("2026-01-01", ["lesson", "distill-of:a"]),
                ("2026-01-02", ["lesson", "distill-of:b", "promoted:b"]),
                ("2026-01-03", ["lesson", "x-distill-of:c", "x-promoted:c"]),
            ],
            2,
            2,
        ),
        ([(None, ["lesson", "distill-of:a", "promoted:a"])], None, None),
    ],
)
def test_grooming_prefilter_preserves_timestamp_semantics(rows, distill_day, promo_day):
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb

    values = ", ".join("(%s::timestamptz, %s::jsonb)" for _ in rows)
    fixtures = (
        f"memory_rows(created_at, tags) AS (VALUES {values}), "
        "wiki_rows(tended) AS (VALUES ('2026-01-04T00:00:00+00'::timestamptz)), "
    )
    query = (
        _grooming_sql().replace("%", "%%").replace("FROM memories", "FROM memory_rows")
    )
    query = query.replace("FROM wiki.pages", "FROM wiki_rows")
    query = "WITH " + fixtures + query.removeprefix("WITH ")
    parameters = [
        value
        for timestamp, tags in rows
        for value in (
            f"{timestamp}T00:00:00+00" if timestamp else None,
            Jsonb(tags),
        )
    ]
    # conftest supplies an isolated DATABASE_URL; standalone runs need a DSN.
    database_url = (
        os.environ.get("CORTEX_TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        result = connection.execute(query, parameters).fetchone()

    def expected(day):
        return datetime(2026, 1, day, tzinfo=timezone.utc) if day else None

    assert result == {
        "wiki_last": expected(4),
        "distill_last": expected(distill_day),
        "promo_last": expected(promo_day),
    }


def test_session_start_queries_disable_jit_for_their_own_transaction_only():
    """SessionStart's queries run with ``SET LOCAL jit = off`` inside their own
    one-statement transaction (ADR-1112: the hook has no connection of its
    own to configure), and never touch the process environment."""
    from mcp_server.infrastructure import hook_queries

    environment = dict(os.environ)
    calls: list[str] = []
    conn = Mock()
    transaction = conn.transaction.return_value
    transaction.__enter__ = Mock(side_effect=lambda *a: calls.append("BEGIN"))
    transaction.__exit__ = Mock(side_effect=lambda *a: calls.append("END"))

    def execute(sql, params=()):
        calls.append(sql)
        result = Mock()
        result.fetchall.return_value = [{"c": 3}]
        return result

    conn.execute.side_effect = execute
    assert hook_queries.session_memory_count(conn) == 3
    assert calls == [
        "BEGIN",
        "SET LOCAL jit = off",
        "SELECT COUNT(*) as c FROM memories",
        "END",
    ]
    for op in (
        hook_queries.session_curation_sample,
        hook_queries.session_grooming_ages,
        hook_queries.session_active_checkpoint,
    ):
        calls.clear()
        op(conn)
        assert calls[:2] == ["BEGIN", "SET LOCAL jit = off"]
        assert calls[-1] == "END"
    assert dict(os.environ) == environment
