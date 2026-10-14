"""`cortex doctor` check: the pgvector library can scan HNSW iteratively.

The store refuses to start without ``hnsw.iterative_scan`` (pgvector >=
0.8.0); this check names the cause before a server or hook trips on it.

source: ADR-1105"""

from __future__ import annotations

import os
from typing import Any, Callable

from mcp_server.infrastructure.pg_iterative_scan import require_iterative_scan

_NAME = "pgvector >= 0.8.0 (hnsw.iterative_scan)"
_FIX = (
    "Upgrade pgvector to 0.8.0 or later (macOS: `brew upgrade pgvector`; "
    "Linux: the PGDG package postgresql-<major>-pgvector, or "
    "https://github.com/pgvector/pgvector#installation), restart "
    "PostgreSQL, then `ALTER EXTENSION vector UPDATE;`"
)


def pgvector_iterative_scan(check: Callable[..., Any]) -> Any:
    """Build the doctor ``Check`` from the loaded pgvector library.

    Pre-condition: ``check`` is doctor's ``Check`` constructor.
    Post-condition: ok iff the library behind DATABASE_URL defines
    ``hnsw.iterative_scan``; any other failure is reported, not raised."""
    # The missing setting is named first: without a URL there is nothing to
    # connect to, whatever the driver (CI's SQLite job has no psycopg).
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return check(_NAME, False, "DATABASE_URL not set", "")
    try:
        import psycopg  # noqa: PLC0415 — source: ADR-0322
        from psycopg.rows import DictRow, dict_row  # noqa: PLC0415 — source: ADR-0322
    except ImportError:
        return check(_NAME, False, "psycopg not installed", "")
    try:
        with psycopg.Connection[DictRow].connect(
            url, connect_timeout=5, row_factory=dict_row
        ) as conn:
            require_iterative_scan(conn.cursor())
            row = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
    except RuntimeError as exc:
        return check(_NAME, False, str(exc), _FIX)
    except Exception as exc:  # noqa: BLE001 — source: ADR-0322
        return check(_NAME, False, f"{type(exc).__name__}: {exc}", _FIX)
    version = row["extversion"] if row else "unknown"
    return check(_NAME, True, f"library defines it (extension {version})")
