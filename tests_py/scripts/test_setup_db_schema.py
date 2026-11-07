"""scripts/setup_db.py ``_init_schema``: a failed DDL statement fails the setup.

Before ADR-1114 every statement error was logged as a "schema warning" and the
result was still ``(True, "")``: a database missing a table or index reported
ready (owner rule: no silent degradation; PR #748 review, minor).

source: ADR-1114
source: ADR-0784
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Conn:
    def __init__(self, failing: set[str]) -> None:
        self.failing, self.ran = failing, []

    def execute(self, ddl: str) -> None:
        self.ran.append(ddl)
        if ddl in self.failing:
            raise RuntimeError(f"boom: {ddl}")

    def close(self) -> None:
        pass


@pytest.fixture
def init_schema(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    import setup_db
    from mcp_server.infrastructure import pg_schema

    monkeypatch.setattr(
        pg_schema, "get_all_ddl", lambda: ["CREATE A", "CREATE B", "CREATE C"]
    )

    def run(failing: set[str]):
        conn = _Conn(failing)
        fake = types.ModuleType("psycopg")
        fake.connect = lambda *_a, **_k: conn
        rows = types.ModuleType("psycopg.rows")
        rows.dict_row = object()
        monkeypatch.setitem(sys.modules, "psycopg", fake)
        monkeypatch.setitem(sys.modules, "psycopg.rows", rows)
        return setup_db._init_schema("postgresql://x/cortex"), conn

    return run


def test_every_statement_succeeding_is_ready(init_schema):
    (ok, error), conn = init_schema(set())
    assert (ok, error) == (True, "")
    assert conn.ran == ["CREATE A", "CREATE B", "CREATE C"]


def test_one_failed_statement_fails_and_names_it_after_running_all(init_schema):
    (ok, error), conn = init_schema({"CREATE B"})
    assert ok is False
    assert "1 schema statements failed" in error and "boom: CREATE B" in error
    assert conn.ran == ["CREATE A", "CREATE B", "CREATE C"]
