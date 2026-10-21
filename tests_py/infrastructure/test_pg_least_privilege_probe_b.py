"""The audit's probe B (docs/audits/2026-10-21-three-pillar-audit.md, E12 and
Track 0.3) on the broker (ADR-1112 increment 6).

A private cluster provisioned with the one command
``scripts/setup_least_privilege.py``: a migration role owning the database, a
runtime role with CONNECT only, the extensions created by the administrator.
The broker migrates as the owner and serves as the runtime role; the
``remember`` and ``recall`` tool handlers then work through it. On main the
runtime role could not open the store at all (97 swallowed failures, then
``InsufficientPrivilege`` on ``schema_meta``, audit E12). Before and after
the broker's grants the runtime role still cannot create a table.

source: ADR-1112 (least privilege)
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from tests_py import _pg_private_cluster as cluster

psycopg = pytest.importorskip("psycopg")

pytestmark = [
    pytest.mark.skipif(not cluster.available(), reason="initdb/pg_ctl not on PATH"),
    pytest.mark.skipif(sys.platform == "win32", reason="Unix transport"),
]

_REPO = Path(__file__).resolve().parents[2]


def _cannot_create_tables(url: str) -> bool:
    with psycopg.connect(url, autocommit=True) as conn:
        try:
            conn.execute("CREATE TABLE probe_b_ddl (i integer)")
        except psycopg.errors.InsufficientPrivilege:
            return True
    return False


def _provision(maint: str) -> tuple[str, str]:
    """The one command, as the administrator; returns (runtime, owner) URLs."""
    done = subprocess.run(
        [
            sys.executable,
            "scripts/setup_least_privilege.py",
            "--admin-url",
            maint,
            "--database",
            "probe_b",
        ],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    host = maint.rpartition("/")[0].replace("postgresql://", "")
    return (
        f"postgresql://cortex_runtime@{host}/probe_b",
        f"postgresql://cortex_migrate@{host}/probe_b",
    )


def _remember_then_recall(memory_store) -> tuple[dict, dict]:
    from mcp_server.handlers import recall, remember  # noqa: PLC0415

    memory_store.reset_shared_store()
    try:
        stored = asyncio.run(
            remember.handler(
                {"content": "probe B: the runtime role writes", "force": True}
            )
        )
        found = asyncio.run(recall.handler({"query": "probe B runtime role"}))
    finally:
        memory_store.reset_shared_store()
    return stored, found


def test_a_dml_only_runtime_role_remembers_and_recalls_through_the_broker(
    broker_env, monkeypatch, tmp_path
):
    from mcp_server.infrastructure import memory_store  # noqa: PLC0415

    root, children = broker_env
    with cluster.private_cluster(tmp_path / "pg", max_connections=40) as maint:
        runtime, owner = _provision(maint)
        assert _cannot_create_tables(runtime)
        monkeypatch.setenv("DATABASE_URL", runtime)
        monkeypatch.setenv("CORTEX_MIGRATION_DATABASE_URL", owner)
        monkeypatch.delenv("CORTEX_STORE_IN_PROCESS", raising=False)
        monkeypatch.setattr(memory_store, "CLAUDE_DIR", root)
        stored, found = _remember_then_recall(memory_store)
        assert stored.get("stored") or stored.get("memory_id"), stored
        assert any("probe B" in m.get("content", "") for m in found["memories"]), found
        assert len(children) == 1  # one broker, started by the first handler
        assert _cannot_create_tables(runtime)  # the grants are data access only
        with psycopg.connect(owner) as conn:
            owners = conn.execute(
                "SELECT DISTINCT tableowner FROM pg_tables"
                " WHERE schemaname IN ('public', 'wiki')"
            ).fetchall()
        assert owners == [("cortex_migrate",)]
