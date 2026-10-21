"""Census of failing schema statements, before and after ADR-1112 increment 1.

    python scripts/repro_ddl_census.py

On a private cluster (never the live store), for three database setups
(superuser owner; non-superuser owner without extensions; non-superuser owner
with the extensions created by an administrator), each run twice (fresh, then
a full re-run over the existing schema):

* ``before``: every statement of ``get_all_ddl()`` executed in order on one
  autocommit connection, failures collected: what main's runner did;
* ``after``: ``pg_migrations.apply_schema`` (prerequisite step, then the
  statements, recorded only when none failed).

Prints the counts, grouped by PostgreSQL error, and appends them to the
append-only experiment log.

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# source: ADR-1112 repository root, from this file's location
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from mcp_server.infrastructure import pg_migrations as mig  # noqa: E402
from mcp_server.infrastructure import schema_versions as sv  # noqa: E402
from tests_py import _pg_private_cluster as cluster  # noqa: E402

# source: ADR-1112 the append-only experiment log
LOG = ROOT / "docs" / "verification" / "connection-broker" / "experiment-log.md"


def _before(url: str) -> dict:
    errors: Counter[str] = Counter()
    with psycopg.connect(url, autocommit=True) as conn:
        for ddl in mig.get_all_ddl():
            try:
                conn.execute(ddl)
            except psycopg.Error as exc:
                errors[f"{type(exc).__name__}: {str(exc).splitlines()[0][:80]}"] += 1
    return {"failed": sum(errors.values()), "by_error": dict(errors.most_common())}


def _after(url: str) -> dict:
    try:
        return {"failed": 0, "applied": mig.apply_schema(url)}
    except sv.MigrationFailedError as exc:
        return {"failed": len(exc.failures), "first": exc.failures[:1]}
    except sv.SchemaError as exc:
        return {"failed": 0, "refused_before_any_statement": type(exc).__name__}


def _setups(maint: str) -> dict[str, str]:
    base = maint.rsplit("/", 1)[0]
    host = base.split("//")[1]
    urls = {}
    with psycopg.connect(maint, autocommit=True) as conn:
        for runner in ("before", "after"):
            conn.execute(f"CREATE DATABASE su_{runner}")
            urls[f"{runner}/superuser"] = f"{base}/su_{runner}"
            for kind in ("noext", "ext"):
                role = f"{kind}_{runner}_owner"
                conn.execute(f"CREATE ROLE {role} LOGIN NOSUPERUSER")
                conn.execute(f"CREATE DATABASE {kind}_{runner} OWNER {role}")
                urls[f"{runner}/owner-{kind}"] = (
                    f"postgresql://{role}@{host}/{kind}_{runner}"
                )
    for runner in ("before", "after"):
        with psycopg.connect(f"{base}/ext_{runner}", autocommit=True) as conn:
            conn.execute("CREATE EXTENSION vector")
            conn.execute("CREATE EXTENSION pg_trgm")
    return urls


def _rerun_marker(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        if conn.execute("SELECT to_regclass('public.schema_meta')").fetchone()[0]:
            conn.execute("UPDATE schema_meta SET ddl_hash = 'force-a-full-rerun'")


def main() -> int:
    results: dict = {"statements": len(mig.get_all_ddl())}
    with tempfile.TemporaryDirectory(prefix="cortex-ddl-census-") as scratch:
        with cluster.private_cluster(Path(scratch), 20) as maint:
            for key, url in _setups(maint).items():
                run = _before if key.startswith("before") else _after
                results[f"{key}/fresh"] = run(url)
                _rerun_marker(url)
                results[f"{key}/rerun"] = run(url)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = "\n".join(f"- {k}: `{json.dumps(v)}`" for k, v in results.items())
    with LOG.open("a", encoding="utf-8") as log:
        log.write(
            f"\n### {stamp} DDL census\n\n- command: "
            f"`python scripts/repro_ddl_census.py`\n{lines}\n"
        )
    print(lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
