"""Audit probes on real roles, on a private cluster (ADR-1112).

The shared test server's role is a superuser and roles are cluster-wide, so
these probes create their roles in a throwaway cluster
(``tests_py/_pg_private_cluster.py``), never on the developer's server.
Probe names follow docs/audits/2026-10-21-three-pillar-audit.md (E12, E13).

* Probe D: a database owner that is not a superuser cannot create the
  ``vector`` extension; the migration must fail loudly and record nothing
  (on main it swallowed 58 failures and recorded the fingerprint).

source: ADR-1112
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests_py import _pg_private_cluster as cluster

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(
    not cluster.available(), reason="initdb/pg_ctl not on PATH"
)

_REPO = Path(__file__).resolve().parents[2]
# source: ADR-1112 room for the probes' connections only
_MAX_CONNECTIONS = 30


@pytest.fixture(scope="module")
def maint(tmp_path_factory) -> Iterator[str]:
    with cluster.private_cluster(
        tmp_path_factory.mktemp("roles"), _MAX_CONNECTIONS
    ) as url:
        yield url


def _owned_database(maint: str, name: str, role: str) -> str:
    with psycopg.connect(maint, autocommit=True) as conn:
        conn.execute(f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
        conn.execute(f"CREATE DATABASE {name} OWNER {role}")
    host = maint.split("@")[-1] if "@" in maint else maint.split("//")[1]
    return f"postgresql://{role}@{host.rsplit('/', 1)[0]}/{name}"


def _recorded(maint: str, name: str):
    with psycopg.connect(maint.rsplit("/", 1)[0] + "/" + name, autocommit=True) as conn:
        return conn.execute(
            "SELECT to_regclass('public.schema_version'),"
            " to_regclass('public.schema_meta')"
        ).fetchone()


def _tables(maint: str, name: str):
    with psycopg.connect(maint.rsplit("/", 1)[0] + "/" + name, autocommit=True) as conn:
        return conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname IN ('public', 'wiki')"
        ).fetchone()[0]


def _migrate_cli(url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mcp_server.migrate"],
        cwd=_REPO,
        env=dict(os.environ, DATABASE_URL=url),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _force_rerun(maint: str, name: str) -> None:
    with psycopg.connect(maint.rsplit("/", 1)[0] + "/" + name, autocommit=True) as conn:
        conn.execute("UPDATE schema_meta SET ddl_hash = 'force-a-full-rerun'")


def test_probe_d_missing_extension_stops_before_any_statement(maint):
    """On main: 1 privilege failure (vector is untrusted) cascaded into 58
    failed statements and the fingerprint was recorded (audit E13)."""
    from mcp_server.infrastructure import pg_migrations as mig  # noqa: PLC0415 — PG-only import
    from mcp_server.infrastructure import schema_versions as sv  # noqa: PLC0415 — next to the PG-only import

    url = _owned_database(maint, "probe_d", "probe_d_owner")
    with pytest.raises(sv.MigrationPrerequisiteError, match="CREATE EXTENSION vector"):
        mig.apply_schema(url)
    assert _recorded(maint, "probe_d") == (None, None)
    assert _tables(maint, "probe_d") == 0  # no statement ran
    done = _migrate_cli(url)
    assert done.returncode == 1
    assert "No statement was applied and nothing was recorded" in done.stderr


@pytest.mark.parametrize("owner_is_superuser", [True, False])
def test_fresh_database_migrates_with_zero_failures_and_reruns_clean(
    maint, owner_is_superuser
):
    """Zero failed statements on a fresh database and on a full re-run of the
    same statements over an existing schema (experiment log entry 11)."""
    from mcp_server.infrastructure import pg_migrations as mig  # noqa: PLC0415 — PG-only import

    name = "fresh_su" if owner_is_superuser else "fresh_owner"
    if owner_is_superuser:
        with psycopg.connect(maint, autocommit=True) as conn:
            conn.execute(f"CREATE DATABASE {name}")
        url = maint.rsplit("/", 1)[0] + "/" + name
    else:
        url = _owned_database(maint, name, f"{name}_role")
        with psycopg.connect(
            maint.rsplit("/", 1)[0] + "/" + name, autocommit=True
        ) as conn:
            conn.execute("CREATE EXTENSION vector")  # the administrator's step
    statements = len(mig.get_all_ddl())
    assert mig.apply_schema(url) == statements  # raises on any failed statement
    _force_rerun(maint, name)
    assert mig.apply_schema(url) == statements  # every statement again, none failed
    assert mig.apply_schema(url) == 0
