#!/usr/bin/env python3
"""Cortex database setup — auto-detect, create, and initialize PostgreSQL.

Designed to be run non-interactively by the plugin SessionStart hook.
Outputs status to stderr (diagnostic) and a single JSON result to stdout.

Exit codes:
  0 — database ready (created or already existed)
  1 — PostgreSQL not running or not installed (server unreachable)
  2 — could not create database or extensions
  3 — schema initialization failed
  4 — authentication/authorization failure (server up, bad credentials/role)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys


def _safe_ident(name: str) -> str:
    """Validate a database identifier contains only safe characters."""
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
        raise ValueError(f"Unsafe database name: {name!r}")
    return name


def _log(msg: str) -> None:
    print(f"[cortex-setup] {msg}", file=sys.stderr)


def _result(status: str, message: str, **extra: object) -> None:
    """Print JSON result to stdout and exit."""
    code = {
        "ready": 0,
        "needs_install": 1,
        "create_failed": 2,
        "schema_failed": 3,
        "auth_failed": 4,
    }
    out = {"status": status, "message": message, **extra}
    print(json.dumps(out))
    sys.exit(code.get(status, 1))


def _get_database_url() -> str:
    """Resolve DATABASE_URL from environment or default.

    Treats an empty value or an unexpanded ``${...}`` token as unset.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or "${" in url:
        return "postgresql://127.0.0.1:5432/cortex"
    return url


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
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


# Substrings that mark a PostgreSQL connection failure as authentication/
# authorization (not a missing database or a down server). Source: libpq
# error messages — postgresql.org/docs/current/protocol-error-fields.html
_AUTH_SIGNATURES = (
    "password authentication failed",
    "no password supplied",
    "authentication failed",
    "does not exist",  # role "x" does not exist
    "permission denied",
    "must be superuser",
    "must be member of",
)


def _is_auth_error(stderr: str) -> bool:
    """True if stderr indicates an auth/authorization failure (not db-absent)."""
    s = stderr.lower()
    return any(sig in s for sig in _AUTH_SIGNATURES)


def _probe_database(host: str, port: str, dbname: str) -> tuple[str, str]:
    """Probe for the target database.

    Returns (state, detail) where state is one of:
      exists | absent | auth_failed | error
    """
    psql = shutil.which("psql")
    if not psql:
        return "error", "psql not found on PATH"
    try:
        r = subprocess.run(
            [
                psql,
                "-h",
                host,
                "-p",
                port,
                "-d",
                "postgres",
                "-tAc",
                f"SELECT 1 FROM pg_database WHERE datname = '{_safe_ident(dbname)}'",
            ],
            capture_output=True,
            timeout=5,
            text=True,
        )
    except Exception as e:
        return "error", str(e)
    if r.returncode != 0:
        detail = r.stderr.strip()
        return ("auth_failed" if _is_auth_error(detail) else "error"), detail
    return ("exists" if "1" in r.stdout else "absent"), ""


def _create_db(host: str, port: str, dbname: str) -> tuple[bool, str]:
    """Create the database. Returns (ok, stderr)."""
    createdb = shutil.which("createdb")
    if not createdb:
        return False, "createdb not found on PATH"
    try:
        r = subprocess.run(
            [createdb, "-h", host, "-p", port, dbname],
            capture_output=True,
            timeout=10,
            text=True,
        )
        return r.returncode == 0, r.stderr.strip()
    except Exception as e:
        return False, str(e)


def _create_extensions(host: str, port: str, dbname: str) -> tuple[bool, str]:
    """Create pgvector and pg_trgm extensions."""
    psql = shutil.which("psql")
    if not psql:
        return False, "psql not found"
    try:
        r = subprocess.run(
            [
                psql,
                "-h",
                host,
                "-p",
                port,
                "-d",
                dbname,
                "-c",
                "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            ],
            capture_output=True,
            timeout=10,
            text=True,
        )
        if r.returncode != 0:
            return False, r.stderr.strip()
        return True, ""
    except Exception as e:
        return False, str(e)


def _init_schema(database_url: str) -> tuple[bool, str]:
    """Run full schema initialization via psycopg.

    Executes each DDL statement independently so a single failure
    (e.g. extension missing, column type mismatch) doesn't prevent
    the remaining tables and functions from being created.
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
        from mcp_server.infrastructure.pg_schema import get_all_ddl

        conn = psycopg.connect(database_url, row_factory=dict_row, autocommit=True)
        errors: list[str] = []
        for ddl in get_all_ddl():
            try:
                conn.execute(ddl)
            except Exception as stmt_err:
                first_line = ddl.strip().split("\n")[0][:60]
                errors.append(f"{first_line}: {stmt_err}")
        conn.close()
        if errors:
            _log(f"Schema warnings ({len(errors)} statements had issues):")
            for e in errors[:5]:
                _log(f"  {e}")
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


def _server_down_message(host: str, port: str) -> str:
    """Message for an unreachable server — includes the stale-lock case."""
    return (
        f"PostgreSQL is not accepting connections at {host}:{port}.\n"
        "\n"
        "If it was working before, an unclean shutdown can leave a stale lock\n"
        "that blocks restart (the PID in postmaster.pid gets reused by another\n"
        "process, so PostgreSQL refuses to start):\n"
        "  brew services list                 # look for postgresql@NN in 'error'\n"
        "  rm -f $(brew --prefix)/var/postgresql@17/postmaster.pid\n"
        "  brew services restart postgresql@17\n"
        "\n"
        "If it is not installed yet:\n"
        "  # macOS\n"
        "  brew install postgresql@17 pgvector && brew services start postgresql@17\n"
        "  # Ubuntu/Debian\n"
        "  sudo apt install postgresql postgresql-server-dev-all\n"
        "  sudo systemctl start postgresql\n"
        "  # pgvector: https://github.com/pgvector/pgvector#installation\n"
        "\n"
        "Then restart Claude Code."
    )


def _auth_message(host: str, port: str, dbname: str, detail: str) -> str:
    """Message for an auth/authorization failure — server up, creds wrong."""
    return (
        f"PostgreSQL at {host}:{port} is running, but the connection was "
        f"refused for authentication/authorization reasons:\n"
        f"  {detail}\n"
        "\n"
        "The database may well exist — this is a credentials/role problem, not a\n"
        "missing database. Check the user, password, and role in your DATABASE_URL\n"
        "(set it via the plugin's database_url config), and that the role may "
        f"connect to '{dbname}'."
    )


def main() -> None:
    """Auto-detect and set up PostgreSQL for Cortex."""
    url = _get_database_url()
    info = _parse_db_url(url)
    host, port, dbname = info["host"], info["port"], info["dbname"]

    _log(f"Checking PostgreSQL at {host}:{port}/{dbname}")

    # Step 1: Is the server reachable at all?
    if not _pg_is_running(host, port):
        _result("needs_install", _server_down_message(host, port))

    # Step 2: Probe the database — distinguishes absent from auth failure.
    state, detail = _probe_database(host, port, dbname)
    if state == "auth_failed":
        _result("auth_failed", _auth_message(host, port, dbname, detail))
    if state == "error":
        _result("create_failed", f"Could not query PostgreSQL: {detail}")
    if state == "absent":
        _log(f"Database '{dbname}' not found, creating...")
        ok, err = _create_db(host, port, dbname)
        if not ok:
            if _is_auth_error(err):
                _result("auth_failed", _auth_message(host, port, dbname, err))
            _result(
                "create_failed",
                f"Could not create database '{dbname}': {err or 'unknown error'}\n"
                f"Try manually: createdb -h {host} -p {port} {dbname}",
            )
        _log(f"Database '{dbname}' created")

    # Step 3: Create extensions
    ok, err = _create_extensions(host, port, dbname)
    if not ok:
        _result(
            "create_failed",
            f"Could not create extensions (pgvector/pg_trgm): {err}\n"
            f"Install pgvector: brew install pgvector (macOS) or "
            f"see https://github.com/pgvector/pgvector#installation",
        )

    _log("Extensions ready (pgvector, pg_trgm)")

    # Step 4: Initialize schema
    ok, err = _init_schema(url)
    if not ok:
        _result("schema_failed", f"Schema initialization failed: {err}")

    _log("Schema initialized")

    # Step 5: Check state
    memory_count = _count_memories(url)
    session_count = _count_session_files()

    _result(
        "ready",
        "Database ready",
        **{
            "database": dbname,
            "memories": memory_count,
            "session_files": session_count,
            "needs_backfill": memory_count == 0 and session_count > 0,
        },
    )


if __name__ == "__main__":
    main()
