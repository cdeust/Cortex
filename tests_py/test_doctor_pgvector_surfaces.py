"""The pgvector >= 0.8.0 check reaches every user-facing diagnostic.

``cortex doctor`` runs it from ``doctor.CHECKS``; the ``check_setup`` MCP
tool is a facade over the same list; ``cortex doctor mcp`` reports it too.
Live PG for the passing case (throwaway test database via conftest);
skipped on SQLite.

source: ADR-1105
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.doctor_mcp import _check_pg_iterative_scan, collect_mcp_report
from mcp_server.doctor_pgvector import _NAME
from mcp_server.handlers.check_setup import handler
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store


@pytest.fixture
def pg_backend():
    settings = get_memory_settings()
    shared = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    if not hasattr(shared, "batch_pool"):
        pytest.skip("pgvector check runs on the PostgreSQL backend only")


def test_check_setup_tool_reports_pgvector_iterative_scan(pg_backend):
    result = asyncio.run(handler())
    check = next(c for c in result["checks"] if c["name"] == _NAME)
    assert check["ok"] is True
    assert check["optional"] is False


def test_doctor_mcp_reports_pgvector_iterative_scan(pg_backend):
    report = collect_mcp_report()
    check = next(c for c in report.checks if c.name == _NAME)
    assert check.ok is True
    assert check.severity == "ok"


def test_doctor_mcp_pgvector_check_fails_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    check = _check_pg_iterative_scan()
    assert check.ok is False
    assert check.severity == "fail"
    assert "DATABASE_URL not set" in check.detail
