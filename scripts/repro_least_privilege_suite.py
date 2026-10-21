#!/usr/bin/env python3
"""The PostgreSQL suite as a non-superuser, one command (ADR-1112 increment 6).

    python scripts/repro_least_privilege_suite.py [pytest arguments]

Starts a private cluster from the PATH binaries, creates a role with LOGIN
and CREATEDB and without SUPERUSER, installs ``vector`` and ``pg_trgm`` in
``template1`` as the administrator (``vector`` is not a trusted extension),
creates the role's test database, and runs ``pytest`` (default: the whole
suite) against it. Appends the role's attributes, the pytest exit code and
its summary line to the experiment log. The CI job
``test-pg-least-privilege`` is the same run on the runner's server.

source: ADR-1112 (least privilege); three-pillar audit Track 0.3, E14
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from tests_py import _pg_private_cluster as cluster  # noqa: E402

LOG = ROOT / "docs" / "verification" / "connection-broker" / "experiment-log.md"
# source: ADR-1112 the role the suite runs as (no SUPERUSER)
ROLE = "cortex_lp"
# source: three-pillar audit Track 0.3 (room for the suite's per-test brokers)
_MAX_CONNECTIONS = 100


def _provision(maint: str) -> tuple[str, str]:
    with psycopg.connect(maint, autocommit=True) as conn:
        conn.execute(f"CREATE ROLE {ROLE} LOGIN CREATEDB NOSUPERUSER")
        conn.execute(f"CREATE DATABASE {ROLE}_test OWNER {ROLE}")
        attributes = conn.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles"
            " WHERE rolname = %s",
            (ROLE,),
        ).fetchone()
    base = maint.rpartition("/")[0]
    for database in ("template1", f"{ROLE}_test"):
        with psycopg.connect(f"{base}/{database}", autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    host = base.replace("postgresql://", "")
    return f"postgresql://{ROLE}@{host}/{ROLE}_test", str(attributes)


def _run_suite(pytest_args: list[str]) -> tuple[subprocess.CompletedProcess, str]:
    """The suite on a private cluster, as the role without SUPERUSER."""
    with tempfile.TemporaryDirectory(prefix="cortex-lp-") as scratch:
        with cluster.private_cluster(Path(scratch), _MAX_CONNECTIONS) as maint:
            url, attributes = _provision(maint)
            env = {**os.environ, "CORTEX_TEST_DATABASE_URL": url, "DATABASE_URL": url}
            done = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    *pytest_args,
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
    return done, attributes


def main() -> int:
    pytest_args = sys.argv[1:] or ["tests_py"]
    done, attributes = _run_suite(pytest_args)
    lines = done.stdout.strip().splitlines()
    summary = lines[-1] if lines else ""
    failed = [line for line in lines if line.startswith(("FAILED", "ERROR"))]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    entry = [
        f"\n### least-privilege suite {stamp}"
        " (`python scripts/repro_least_privilege_suite.py`)\n",
        f"- role `{ROLE}` (rolsuper, rolcreatedb, rolcreaterole) = {attributes}",
        f"- pytest {' '.join(pytest_args)}: exit {done.returncode}, `{summary}`",
        *[f"- {line[:200]}" for line in failed[:40]],
    ]
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(entry) + "\n")
    print(summary)
    for line in failed:
        print(line)
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
