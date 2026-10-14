"""The iterative-scan capability check and session setting, without a database.

A pgvector library without ``hnsw.iterative_scan`` (before 0.8.0) drops the
SET with a WARNING only (review of #754), so every vector query would stay
lossy without a word: the store refuses to start instead.

source: ADR-1105
"""

from __future__ import annotations

import pytest

from mcp_server.doctor import Check, _pgvector_iterative_scan
from mcp_server.infrastructure.pg_iterative_scan import (
    enable_iterative_scan,
    require_iterative_scan,
)


class _SettingCursor:
    """Answers the library load and the setting lookup."""

    def __init__(self, setting: str | None) -> None:
        self._setting = setting
        self.queries: list[str] = []

    def execute(self, sql: str) -> None:
        self.queries.append(sql)

    def fetchone(self):
        return {"setting": self._setting}

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class _Connection:
    def __init__(self, setting: str | None) -> None:
        self.cur = _SettingCursor(setting)

    def cursor(self, row_factory=None):
        return self.cur


def test_a_library_without_the_parameter_is_refused():
    cur = _SettingCursor(None)
    with pytest.raises(RuntimeError, match=r"pgvector >= 0\.8\.0"):
        require_iterative_scan(cur)
    assert cur.queries[0] == "SELECT '[1]'::vector"  # the library is loaded first


def test_the_check_reads_the_loaded_library_not_extversion():
    cur = _SettingCursor("off")
    require_iterative_scan(cur)
    assert "current_setting('hnsw.iterative_scan', true)" in cur.queries[1]
    assert not any("extversion" in q for q in cur.queries)


def test_the_session_setting_follows_the_check():
    conn = _Connection("off")
    enable_iterative_scan(conn)
    assert conn.cur.queries[-1] == "SET hnsw.iterative_scan = relaxed_order"


def test_no_setting_is_sent_to_a_library_that_lacks_it():
    conn = _Connection(None)
    with pytest.raises(RuntimeError):
        enable_iterative_scan(conn)
    assert not any(q.startswith("SET") for q in conn.cur.queries)


class _Server(_Connection):
    """psycopg.connect(...) stand-in: a context manager over _Connection."""

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def test_doctor_names_the_missing_capability(monkeypatch):
    pytest.importorskip("psycopg")  # the [postgresql] extra; absent on SQLite-only
    monkeypatch.setattr("psycopg.Connection.connect", lambda *a, **kw: _Server(None))
    monkeypatch.setenv("DATABASE_URL", "postgresql://doctor.invalid/cortex")
    check = _pgvector_iterative_scan()
    assert isinstance(check, Check)
    assert not check.ok and "pgvector >= 0.8.0" in check.detail
    assert "pgvector" in check.fix and not check.optional


def test_doctor_without_database_url_fails(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    check = _pgvector_iterative_scan()
    assert not check.ok and check.detail == "DATABASE_URL not set"
