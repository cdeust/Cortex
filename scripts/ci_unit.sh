#!/usr/bin/env bash
# One unit suite with both storage implementations available.
# source: .github/actions/test-suite/action.yml (PostgreSQL + sqlite extras)
# source: scripts/launcher_pg_assets.py (audited PostgreSQL/pgvector digests)
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
work="$(umask 077; mktemp -d "${TMPDIR:-/tmp}/cortex-unit.XXXXXX")"
pg_bin=""
cleanup() {
  status=$?
  trap - EXIT
  if [[ "$status" -ne 0 && -f "$work/postgres.log" ]]; then
    cat "$work/postgres.log" >&2
  fi
  if [[ -n "$pg_bin" && -f "$work/cluster/postmaster.pid" ]]; then
    if ! "$pg_bin/pg_ctl" -D "$work/cluster" -m fast -w stop; then
      echo "Failed to stop the unit-test cluster; preserved $work" >&2
      exit 1
    fi
  fi
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

python - "$repo" "$work" <<'PY'
import fcntl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import launcher_pg_assets

work = Path(sys.argv[2])
with (work / "install.lock").open("w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    tree = launcher_pg_assets.install(work / "dist", launcher_pg_assets.host_triple())
(work / "bin-path").write_text(str(tree / "bin"), encoding="utf-8")
PY
pg_bin="$(cat "$work/bin-path")"
"$pg_bin/initdb" -D "$work/cluster" -U cortex --auth=trust --no-locale -E UTF8
mkdir "$work/socket"
# No TCP listener; only this private directory exposes the test database.
"$pg_bin/pg_ctl" -D "$work/cluster" -l "$work/postgres.log" \
  -o "-h '' -k '$work/socket'" -w start

# source: PostgreSQL libpq URI docs, percent-encoded Unix socket host.
DATABASE_URL="$(python - "$work/socket" <<'PY'
import sys
from urllib.parse import quote
print(f"postgresql://cortex@{quote(sys.argv[1], safe='')}/cortex_unit_test")
PY
)"
export DATABASE_URL
export CORTEX_TEST_DATABASE_URL="$DATABASE_URL"
export CORTEX_MEMORY_STORE_BACKEND=postgresql
python - <<'PY'
import os
import psycopg
from psycopg.conninfo import make_conninfo

url = os.environ["DATABASE_URL"]
with psycopg.connect(make_conninfo(url, dbname="postgres"), autocommit=True) as conn:
    conn.execute("CREATE DATABASE cortex_unit_test")
with psycopg.connect(url, autocommit=True) as conn:
    conn.execute("CREATE EXTENSION vector")
    conn.execute("CREATE EXTENSION pg_trgm")
    print("Unit PostgreSQL:", conn.execute("SELECT version()").fetchone()[0])
PY

python -m pytest --tb=short -q -p no:randomly --cov=mcp_server --cov-report=xml "$@"
