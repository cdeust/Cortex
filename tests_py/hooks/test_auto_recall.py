"""End-to-end tests for the auto_recall UserPromptSubmit hook.

Unit-level tests (no PG needed) for the T2-H2 session registry refresh
wiring live in ``test_auto_recall_registry.py`` — this file's module
level ``pytestmark`` skips everything when PG is unreachable, which
would wrongly skip registry-only tests that need no database.

Issue #20 root cause: auto_recall.py queried ``memories.heat`` — a
column that does NOT exist in the storage schema (the stored column
is ``heat_base``; ``heat`` is only a derived projection returned by
``effective_heat()`` and ``recall_memories()``). Every hook firing
swallowed the PG error silently, breaking transparent memory injection.

These tests exercise the hook against a real PG schema with seeded
memories — the smoke layer that would have caught this at write time.

Pre/post:
- pre: PG reachable on test database; pg_trgm + vector + plpgsql loaded.
- post: hook prints injected context to stdout, exits 0, no PG errors
  on stderr.

Skipped automatically when PG is not reachable (CI without pgvector).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests_py.conftest import _USE_PG_STORE, _TEST_DB_URL  # type: ignore
import pathlib


pytestmark = pytest.mark.skipif(
    # Gated on the EFFECTIVE backend, not reachability: these fixtures seed
    # PostgreSQL directly (raw DSN / PG-only migrations) while the product
    # under test reads the resolved store. Under a sqlite-backend run they
    # seeded one store and asserted against another, so they failed for a
    # harness reason rather than a product one. SQLite coverage of these
    # paths needs backend-agnostic fixtures — tracked in #220.
    not _USE_PG_STORE,
    reason="PostgreSQL not available — auto_recall hook needs PG schema",
)


@pytest.fixture()
def _seeded_db():
    """Initialize schema (via PgMemoryStore) and seed 3 known memories.

    Returns the DATABASE_URL so the hook subprocess uses the same DB.
    """
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    # Instantiating PgMemoryStore runs DDL idempotently — including
    # the effective_heat() function definition.
    store = PgMemoryStore(database_url=_TEST_DB_URL)

    import psycopg

    conn = psycopg.connect(_TEST_DB_URL, autocommit=True)
    try:
        # Wipe relevant rows; conftest cleans tables but the autouse
        # fixture has already run at this point.
        conn.execute(
            "DELETE FROM memories WHERE content LIKE %s", ("AUTORECALL_TEST%",)
        )
        rows = [
            ("AUTORECALL_TEST freight delivery routing optimization", 0.9, False),
            ("AUTORECALL_TEST quantum entanglement laboratory protocol", 0.8, False),
            ("AUTORECALL_TEST irrelevant gardening tip about tomatoes", 0.7, False),
        ]
        for content, heat_base, is_benchmark in rows:
            conn.execute(
                "INSERT INTO memories (content, heat_base, heat_base_set_at, "
                "is_benchmark, plasticity, no_decay) "
                "VALUES (%s, %s, NOW(), %s, 1.0, FALSE)",
                (content, heat_base, is_benchmark),
            )
    finally:
        conn.close()

    yield _TEST_DB_URL

    # Cleanup
    try:
        conn = psycopg.connect(_TEST_DB_URL, autocommit=True)
        conn.execute(
            "DELETE FROM memories WHERE content LIKE %s", ("AUTORECALL_TEST%",)
        )
        conn.close()
    except Exception:
        pass

    try:
        store._conn.close()
    except Exception:
        pass


def _run_hook(prompt: str, db_url: str) -> subprocess.CompletedProcess:
    """Pipe a prompt JSON to the hook subprocess and capture output."""
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    payload = json.dumps({"prompt": prompt})
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
    return subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.auto_recall"],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
        timeout=10,
    )


def test_auto_recall_injects_relevant_memory(_seeded_db: str) -> None:
    """A query matching a seeded memory should inject it into stdout.

    Regression for issue #20: the original SELECT referenced ``heat``
    which does not exist as a column. The fixed version uses
    ``effective_heat(m, NOW())`` and must return rows.
    """
    # plainto_tsquery joins terms with AND — every word must appear in
    # the seeded content for FTS to match.
    result = _run_hook("freight delivery routing", _seeded_db)

    # Hook always exits 0 (never blocks user input) — but the meaningful
    # signal is "did stdout receive an injection?"
    assert result.returncode == 0
    assert "column" not in result.stderr.lower(), (
        f"PG column error leaked through: {result.stderr}"
    )
    assert "freight" in result.stdout.lower(), (
        f"Expected matching memory in stdout, got stdout={result.stdout!r} "
        f"stderr={result.stderr!r} db={_seeded_db}"
    )
    assert "Cortex context" in result.stdout


def test_auto_recall_no_match_silent_exit(_seeded_db: str) -> None:
    """An irrelevant query should exit 0 with no injection and no errors."""
    result = _run_hook(
        "completely unrelated topic xyzzy plugh nothingmatches", _seeded_db
    )
    assert result.returncode == 0
    assert "column" not in result.stderr.lower()
    # stdout may be empty or just a header — but no PG error trace
    assert "does not exist" not in result.stderr


def test_auto_recall_does_not_crash_on_short_query(_seeded_db: str) -> None:
    """Short/skip queries must exit 0 cleanly without touching PG."""
    result = _run_hook("ok", _seeded_db)
    assert result.returncode == 0
    assert result.stdout.strip() == ""
