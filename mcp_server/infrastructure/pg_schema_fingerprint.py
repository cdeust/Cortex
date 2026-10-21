"""The schema fingerprint, without a database driver.

Pure on purpose: ``scripts/rebuild_codex_install.py`` checks an installed tree
against this checkout with the interpreter it runs under, which need not have
psycopg (measured 2026-10-21: the system ``python3`` has none).

source: ADR-0545 (fingerprint), ADR-1112 (versioned schema)
"""

from __future__ import annotations

import hashlib

from mcp_server.infrastructure.pg_schema import get_all_ddl


def compute_ddl_hash() -> str:
    """SHA-256 fingerprint of the code's full ordered DDL set."""
    return hashlib.sha256("\n".join(get_all_ddl()).encode("utf-8")).hexdigest()
