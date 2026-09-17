"""Project-scoping tests for the auto_recall PostgreSQL path (issue #604).

Split out of test_auto_recall.py (craftsmanship file-size cap): this file
owns every test that exercises the project predicate itself, against a
real PostgreSQL schema. test_auto_recall.py keeps the FTS/column-shape
regression coverage that is orthogonal to scoping.

The starvation test is the review's required regression: the predicate
must run inside the SQL query, before its own LIMIT (5 =
auto_recall._MAX_MEMORIES + 2). Applied after the fetch instead, more
foreign rows above the heat floor than the LIMIT allows consume the
candidate window and starve the project's own row out of it entirely --
the bug fixed after commit 7f27b418.

Skipped automatically when PG is not reachable (CI without pgvector),
same gate as test_auto_recall.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests_py.conftest import _USE_PG_STORE, _TEST_DB_URL  # type: ignore

# The event "cwd" every seeded row's directory_context is written against
# (issue #604) -- distinct from the subprocess's OS-level cwd (repo_root,
# used only so the hook's own imports resolve), since resolve_project_root
# reads the event field, not os.getcwd().
_SEEDED_CWD = "/tmp/cortex-autorecall-test-project"

# source: auto_recall._MAX_MEMORIES + 2 (the PG query's own LIMIT) -- well
# above it, so a post-fetch filter (the bug) would starve the in-project
# row out of the candidate window entirely.
_FOREIGN_ROW_COUNT = 25


pytestmark = pytest.mark.skipif(
    not _USE_PG_STORE,
    reason="PostgreSQL not available — auto_recall hook needs PG schema",
)


def _run_hook(
    prompt: str, db_url: str, cwd_override: str | None = None
) -> subprocess.CompletedProcess:
    """Pipe a prompt JSON to the hook subprocess and capture output.

    Mirror of test_auto_recall.py's ``_run_hook`` -- ``cwd_override`` sets
    the event's "cwd" field, distinct from the subprocess's own OS-level
    working directory, fixed below to repo_root so the hook's imports
    resolve.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env.pop("CLAUDE_PROJECT_ROOT", None)
    payload = json.dumps({"prompt": prompt, "cwd": cwd_override or _SEEDED_CWD})
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.auto_recall"],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=repo_root,
    )


@pytest.fixture()
def _scope_seeded_db():
    """Four rows exercising every branch of memory_matches_project."""
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    PgMemoryStore(database_url=_TEST_DB_URL)

    import psycopg

    conn = psycopg.connect(_TEST_DB_URL, autocommit=True)
    try:
        conn.execute("DELETE FROM memories WHERE content LIKE %s", ("SCOPETEST%",))
        rows = [
            ("SCOPETEST belongs to another project", "/other/project", False),
            ("SCOPETEST is a global decision", "", True),
            ("SCOPETEST lives at an ancestor of the session cwd", _SEEDED_CWD, False),
            ("SCOPETEST has an empty directory_context", "", False),
        ]
        for content, directory_context, is_global in rows:
            conn.execute(
                "INSERT INTO memories (content, heat_base, heat_base_set_at, "
                "is_benchmark, plasticity, no_decay, directory_context, is_global) "
                "VALUES (%s, 0.9, NOW(), FALSE, 1.0, FALSE, %s, %s)",
                (content, directory_context, is_global),
            )
    finally:
        conn.close()

    yield _TEST_DB_URL

    try:
        conn = psycopg.connect(_TEST_DB_URL, autocommit=True)
        conn.execute("DELETE FROM memories WHERE content LIKE %s", ("SCOPETEST%",))
        conn.close()
    except Exception:
        pass


def test_auto_recall_drops_other_project_row(_scope_seeded_db: str) -> None:
    result = _run_hook("belongs to another project", _scope_seeded_db)
    assert result.returncode == 0
    assert "belongs to another project" not in result.stdout.lower()


def test_auto_recall_keeps_global_row(_scope_seeded_db: str) -> None:
    result = _run_hook("is a global decision", _scope_seeded_db)
    assert result.returncode == 0
    assert "global decision" in result.stdout.lower()


def test_auto_recall_keeps_ancestor_row(_scope_seeded_db: str) -> None:
    """The seeded row's directory_context (_SEEDED_CWD) is an ancestor of
    the subdirectory session cwd this run reports."""
    result = _run_hook(
        "lives at an ancestor of the session cwd",
        _scope_seeded_db,
        cwd_override=f"{_SEEDED_CWD}/subdir",
    )
    assert result.returncode == 0
    assert "ancestor of the session cwd" in result.stdout.lower()


def test_auto_recall_drops_empty_directory_context_row(_scope_seeded_db: str) -> None:
    """An empty directory_context is not a wildcard for every project."""
    result = _run_hook("has an empty directory_context", _scope_seeded_db)
    assert result.returncode == 0
    assert "empty directory_context" not in result.stdout.lower()


@pytest.fixture()
def _starvation_seeded_db():
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    PgMemoryStore(database_url=_TEST_DB_URL)

    import psycopg

    conn = psycopg.connect(_TEST_DB_URL, autocommit=True)
    try:
        conn.execute("DELETE FROM memories WHERE content LIKE %s", ("STARVETEST%",))
        conn.execute(
            "INSERT INTO memories (content, heat_base, heat_base_set_at, "
            "is_benchmark, plasticity, no_decay, directory_context, is_global) "
            "VALUES (%s, 0.5, NOW(), FALSE, 1.0, FALSE, %s, FALSE)",
            ("STARVETEST the project's own decision", _SEEDED_CWD),
        )
        for i in range(_FOREIGN_ROW_COUNT):
            conn.execute(
                "INSERT INTO memories (content, heat_base, heat_base_set_at, "
                "is_benchmark, plasticity, no_decay, directory_context, is_global) "
                "VALUES (%s, 0.99, NOW(), FALSE, 1.0, FALSE, %s, FALSE)",
                (f"STARVETEST foreign row {i}", f"/other/project-{i}"),
            )
    finally:
        conn.close()

    yield _TEST_DB_URL

    try:
        conn = psycopg.connect(_TEST_DB_URL, autocommit=True)
        conn.execute("DELETE FROM memories WHERE content LIKE %s", ("STARVETEST%",))
        conn.close()
    except Exception:
        pass


def test_auto_recall_survives_a_foreign_heavy_pool(_starvation_seeded_db: str) -> None:
    result = _run_hook("STARVETEST", _starvation_seeded_db)
    assert result.returncode == 0
    out = result.stdout.lower()
    assert "the project's own decision" in out, (
        f"in-project row starved out by foreign rows above the heat floor: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "foreign row" not in out
