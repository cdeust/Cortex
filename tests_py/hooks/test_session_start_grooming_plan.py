"""Read-only PostgreSQL fixtures verify grooming timestamps after prefiltering.

source: docs/verification/codex-session-start-query-20261002.md
The fixtures use VALUES inside SELECT; no schema or stored rows are changed.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock, patch

import pytest


def _grooming_sql() -> str:
    source = Path(__file__).resolve().parents[2] / "mcp_server/hooks/session_start.py"
    tree = ast.parse(source.read_text())
    for function in tree.body:
        if (
            isinstance(function, ast.FunctionDef)
            and function.name == "_fetch_grooming_staleness"
        ):
            for call in ast.walk(function):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "execute"
                ):
                    return ast.literal_eval(call.args[0])
    raise AssertionError("grooming query absent")


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


def test_session_start_disables_jit_on_its_connection_without_environment_changes():
    source = Path(__file__).resolve().parents[2] / "mcp_server/hooks/session_start.py"
    function = next(
        node
        for node in ast.parse(source.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == "_connect_pg"
    )
    namespace = {"_DATABASE_URL": "postgresql://test.invalid/banner", "_log": print}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    environment = dict(os.environ)
    connect = Mock()

    class Connection:
        @classmethod
        def __class_getitem__(cls, row_type):
            return cls

    Connection.connect = connect
    driver = ModuleType("psycopg")
    driver.Connection = Connection
    rows = ModuleType("psycopg.rows")
    rows.DictRow = dict
    rows.dict_row = Mock()
    with patch.dict(sys.modules, {"psycopg": driver, "psycopg.rows": rows}):
        assert namespace["_connect_pg"]() is connect.return_value
    assert connect.call_args.kwargs["options"] == "-c jit=off"
    assert connect.call_args.kwargs["autocommit"] is True
    assert dict(os.environ) == environment
