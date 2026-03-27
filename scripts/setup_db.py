#!/usr/bin/env python3
"""Cortex database setup — auto-detect, create, and initialize PostgreSQL.

Designed to be run non-interactively by the plugin SessionStart hook.
Outputs status to stderr (diagnostic) and a single JSON result to stdout.

Exit codes:
  0 — database ready (created or already existed)
  1 — PostgreSQL not running or not installed
  2 — could not create database or extensions
  3 — schema initialization failed
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys


def _log(msg: str) -> None:
    print(f"[cortex-setup] {msg}", file=sys.stderr)


def _result(status: str, message: str, **extra: object) -> None:
    """Print JSON result to stdout and exit."""
    code = {"ready": 0, "needs_install": 1, "create_failed": 2, "schema_failed": 3}
    out = {"status": status, "message": message, **extra}
    print(json.dumps(out))
    sys.exit(code.get(status, 1))


def _get_database_url() -> str:
    """Resolve DATABASE_URL from environment or default."""
    return os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")


def _parse_db_url(url: str) -> dict:
    """Extract host, port, dbname from a PostgreSQL URL."""
    # postgresql://[user[:password]@]host[:port]/dbname
    parts = url.replace("postgresql://", "").split("/")
    dbname = parts[1] if len(parts) > 1 else "cortex"
    hostpart = parts[0]
    if "@" in hostpart:
        hostpart = hostpart.split("@")[1]
    if ":" in hostpart:
        host, port = hostpart.rsplit(":", 1)
    else:
        host, port = hostpart or "localhost", "5432"
    return {"host": host, "port": port, "dbname": dbname}


def _pg_is_running(host: str, port: str) -> bool:
    """Check if PostgreSQL is accepting connections."""
    pg_isready = shutil.which("pg_isready")
    if not pg_isready:
        return False
    try:
        r = subprocess.run(
            [pg_isready, "-h", host, "-p", port],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _db_exists(host: str, port: str, dbname: str) -> bool:
    """Check if the target database exists."""
    psql = shutil.which("psql")
    if not psql:
        return False
    try:
        r = subprocess.run(
            [psql, "-h", host, "-p", port, "-d", "postgres",
             "-tAc", f"SELECT 1 FROM pg_database WHERE datname = '{dbname}'"],
            capture_output=True, timeout=5, text=True,
        )
        return "1" in r.stdout
    except Exception:
        return False


def _create_db(host: str, port: str, dbname: str) -> bool:
    """Create the database."""
    createdb = shutil.which("createdb")
    if not createdb:
        return False
    try:
        r = subprocess.run(
            [createdb, "-h", host, "-p", port, dbname],
            capture_output=True, timeout=10, text=True,
        )
        return r.returncode == 0
    except Exception:
        return False


def _create_extensions(host: str, port: str, dbname: str) -> tuple[bool, str]:
    """Create pgvector and pg_trgm extensions."""
    psql = shutil.which("psql")
    if not psql:
        return False, "psql not found"
    try:
        r = subprocess.run(
            [psql, "-h", host, "-p", port, "-d", dbname,
             "-c", "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"],
            capture_output=True, timeout=10, text=True,
        )
        if r.returncode != 0:
            return False, r.stderr.strip()
        return True, ""
    except Exception as e:
        return False, str(e)


def _init_schema(database_url: str) -> tuple[bool, str]:
    """Run full schema initialization via psycopg."""
    try:
        import psycopg
        from psycopg.rows import dict_row
        from mcp_server.infrastructure.pg_schema import get_all_ddl

        conn = psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
        for ddl in get_all_ddl():
            conn.execute(ddl)
        conn.commit()
        conn.close()
        return True, ""
    except ImportError:
        return False, "psycopg not installed (run: pip install psycopg[binary])"
    except Exception as e:
        return False, str(e)


def _count_memories(database_url: str) -> int:
    """Count existing memories in the database."""
    try:
        import psycopg
        conn = psycopg.connect(database_url, autocommit=True)
        row = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def _count_session_files() -> int:
    """Count JSONL session files in ~/.claude/projects/."""
    from pathlib import Path
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return 0
    count = 0
    for project_dir in projects_dir.iterdir():
        if project_dir.is_dir():
            count += len(list(project_dir.glob("*.jsonl")))
    return count


def main() -> None:
    """Auto-detect and set up PostgreSQL for Cortex."""
    url = _get_database_url()
    info = _parse_db_url(url)
    host, port, dbname = info["host"], info["port"], info["dbname"]

    _log(f"Checking PostgreSQL at {host}:{port}/{dbname}")

    # Step 1: Is PostgreSQL running?
    if not _pg_is_running(host, port):
        _result("needs_install", (
            "PostgreSQL is not running. To set up Cortex:\n"
            "\n"
            "  # macOS\n"
            "  brew install postgresql@17 pgvector\n"
            "  brew services start postgresql@17\n"
            "\n"
            "  # Ubuntu/Debian\n"
            "  sudo apt install postgresql postgresql-server-dev-all\n"
            "  sudo systemctl start postgresql\n"
            "  # Install pgvector: https://github.com/pgvector/pgvector#installation\n"
            "\n"
            "Then restart Claude Code."
        ))

    # Step 2: Does the database exist?
    if not _db_exists(host, port, dbname):
        _log(f"Database '{dbname}' not found, creating...")
        if not _create_db(host, port, dbname):
            _result("create_failed",
                     f"Could not create database '{dbname}'. "
                     f"Try manually: createdb {dbname}")
        _log(f"Database '{dbname}' created")

    # Step 3: Create extensions
    ok, err = _create_extensions(host, port, dbname)
    if not ok:
        _result("create_failed",
                 f"Could not create extensions (pgvector/pg_trgm): {err}\n"
                 f"Install pgvector: brew install pgvector (macOS) or "
                 f"see https://github.com/pgvector/pgvector#installation")

    _log("Extensions ready (pgvector, pg_trgm)")

    # Step 4: Initialize schema
    ok, err = _init_schema(url)
    if not ok:
        _result("schema_failed", f"Schema initialization failed: {err}")

    _log("Schema initialized")

    # Step 5: Check state
    memory_count = _count_memories(url)
    session_count = _count_session_files()

    _result("ready", "Database ready", **{
        "database": dbname,
        "memories": memory_count,
        "session_files": session_count,
        "needs_backfill": memory_count == 0 and session_count > 0,
    })


if __name__ == "__main__":
    main()
