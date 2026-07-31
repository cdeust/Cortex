"""Global test configuration — isolate tests from every real-data root.

Handler/integration tests hit PostgreSQL when available. When PG is not
available (CI without PG, sandboxed environments), falls back to SQLite
with per-test isolation via temporary DB files.

Isolation has three roots, and ALL THREE are redirected unconditionally
before any `mcp_server` module is imported (see `_redirect_real_data_roots`):
the PostgreSQL URL, the SQLite file, and the `~/.claude` filesystem tree.
"""

import asyncio
import importlib.util
import os
import sys
import tempfile

import pytest

from scripts.check_venv_lock_parity import postgresql_extra_drift
import pathlib

# ── Redirect every real-data root — MUST run before importing mcp_server ──
#
# INCIDENT 2026-07-28 (issue #219): isolation used to be conditional on
# PostgreSQL being *unavailable*. On a developer machine where PG is
# reachable AND the SQLite backend is selected, the `if not _USE_PG:` block
# below never ran, so `settings.DB_PATH` resolved to the operator's real
# `~/.claude/methodology/memory.db` (reproduced 2026-07-28: a probe test
# printed `binds to REAL DB = True`). The suite DELETEs every table between
# tests, so running it locally wiped that store to 0 rows.
#
# The filesystem was worse, and unconditional: `consolidate.handler()` calls
# `write_dashboards(WIKI_ROOT)`, which walked the developer's real wiki
# (16,234 files — this is the "suite hangs at 58%" symptom, a slow scan, not
# a deadlock) and WROTE generated pages into
# `~/.claude/methodology/wiki/_dashboards/`.
#
# Both roots derive from `config.CLAUDE_DIR`, so one redirection closes both.
# `mcp_server.infrastructure.config` binds its constants at import time and
# importers do `from ... import METHODOLOGY_DIR` (a value copy, 40 modules),
# so the env var must be set before the first import — conftest.py is loaded
# before any test module, and nothing above this point imports mcp_server.
_TEST_CLAUDE_DIR = tempfile.mkdtemp(prefix="cortex_test_claude_")


def _redirect_real_data_roots() -> str:
    """Point the filesystem root and the SQLite store at a throwaway tree.

    Returns the isolated SQLite path. Unconditional by construction: an
    exported `CORTEX_MEMORY_DB_PATH` / `CORTEX_MEMORY_SQLITE_FALLBACK_PATH`
    is OVERWRITTEN, not respected — the backend a developer selects is their
    choice, the physical location the suite writes to is not.
    """
    os.environ["CORTEX_CLAUDE_DIR"] = _TEST_CLAUDE_DIR
    methodology = pathlib.Path(_TEST_CLAUDE_DIR) / "methodology"
    methodology.mkdir(exist_ok=True, parents=True)
    sqlite_path = str(methodology / "memory.db")
    # Handlers read the deprecated DB_PATH; the store reads
    # SQLITE_FALLBACK_PATH. Both must point at the throwaway file or the
    # unset one falls back to the (now redirected, but explicit is better)
    # default. source: memory_config.py:48-49.
    os.environ["CORTEX_MEMORY_DB_PATH"] = sqlite_path
    os.environ["CORTEX_MEMORY_SQLITE_FALLBACK_PATH"] = sqlite_path
    return sqlite_path


_ISOLATED_SQLITE_PATH = _redirect_real_data_roots()

# Imported AFTER the redirect above, never before: this module binds the
# isolated SQLite path at import time from CORTEX_MEMORY_DB_PATH, which
# _redirect_real_data_roots() has just set. Moving this import higher
# reintroduces the #219 ordering bug.
from tests_py._store_cleanup import (  # noqa: E402
    _clean_all_tables,
    _clean_sqlite_store,
    _reset_all_singletons,
    _TABLES_TO_CLEAN,
)

__all__ = ["_TABLES_TO_CLEAN"]  # re-exported: tests import it from conftest

# On Windows asyncio defaults to ProactorEventLoop, whose GC-time teardown
# emits a noisy "Event loop is closed" PytestUnraisableExceptionWarning that
# can mask real errors. SelectorEventLoop tears down cleanly and matches the
# POSIX default. source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §6.5
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── Resolve test database URL ─────────────────────────────────────────────

_CURRENT_URL = os.environ.get("DATABASE_URL", "")
_IS_CI = os.environ.get("CI", "").lower() in ("true", "1")
_EXPLICIT_TEST_DB_URL = os.environ.get("CORTEX_TEST_DATABASE_URL")

if _IS_CI:
    _TEST_DB_URL = _CURRENT_URL or "postgresql://cortex:cortex@localhost:5432/cortex"
else:
    _TEST_DB_URL = _EXPLICIT_TEST_DB_URL or "postgresql://localhost:5432/cortex_test"

# ── Per-process DB isolation (local dev only) ─────────────────────────────
#
# ROOT CAUSE (reproduced deterministically 3/3 + 3/3, 2026-07-10): every
# worktree/agent defaults to the SAME physical DB (cortex_test). The autouse
# `_test_isolation` fixture below runs unconditional `DELETE FROM <table>`
# before/after EVERY test, in EVERY concurrently-running pytest process. Two
# pytest invocations sharing that DB race: process A's between-test purge
# can delete the row process B just stored, between B's remember() and its
# later recall()/get_memory() call. This produced both previously-reported
# flakes with unrelated proximate symptoms:
#   - test_store_consolidate_recall: recall_result["count"] == 0
#     (see /tmp/wt-flake-hunt/run_b_{1,2,3}.log)
#   - test_memory_count_unchanged_after_validation: store.get_memory() is None
#     (see /tmp/wt-flake-hunt/run_v3_{1,2,3}.log)
# Neither is an intra-suite ordering bug nor an embeddings-backend issue —
# both are inter-process contention on one shared table set. Retrying or
# skipping would hide the race, not fix it (forbidden anti-pattern). The
# correct fix is to give each local pytest process its own throwaway
# database — CI already gets a fresh service-container DB per run, and an
# explicit CORTEX_TEST_DATABASE_URL override is respected verbatim (the
# caller has taken responsibility for isolation).
#
# The creation/cleanup mechanics live in tests_py/_pg_throwaway_db.py (moved
# out to bring this file under coding-standards.md §4.1's 300-line cap;
# issue #276/#287 boy-scout follow-up) — no behavior change, see that
# module's docstring.
from tests_py import _pg_safety_guards, _pg_throwaway_db  # noqa: E402

_CORTEX_TEST_ISOLATE_DB = os.environ.get("CORTEX_TEST_ISOLATE_DB", "1") not in (
    "0",
    "false",
    "False",
)
_OWNED_ISOLATED_DB: tuple[str, str] | None = None  # (maintenance_url, db_name)

if not _IS_CI and _CORTEX_TEST_ISOLATE_DB and not _EXPLICIT_TEST_DB_URL:
    _created = _pg_throwaway_db.create_isolated_test_database(_TEST_DB_URL)
    if _created is not None:
        _TEST_DB_URL, _maint_url, _db_name = _created
        _OWNED_ISOLATED_DB = (_maint_url, _db_name)

os.environ["DATABASE_URL"] = _TEST_DB_URL


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """Drop the throwaway per-process database created above, if any."""
    if _OWNED_ISOLATED_DB is not None:
        _pg_throwaway_db.drop_isolated_database(*_OWNED_ISOLATED_DB)


def _guard_against_venv_lock_drift() -> None:
    """Refuse to run if the postgresql-extra install has drifted from
    ``requirements/ci-postgresql.txt`` (issue #287).

    Same shape as the two guards above: a pure check
    (``postgresql_extra_drift``, unit-tested on its own in
    ``tests_py/scripts/test_check_venv_lock_parity.py``) plus an eager call
    here that turns a silent, version-drift-driven change in the collected
    test count into an immediate, actionable session abort — never a
    quietly-smaller number a contributor trusts over CI's.
    """
    message = postgresql_extra_drift()
    if message is not None:
        pytest.exit(f"REFUSING to run: {message}", returncode=2)


def _pg_available() -> bool:
    """Check if PostgreSQL is reachable."""
    try:
        import psycopg

        conn = psycopg.connect(_TEST_DB_URL, autocommit=True, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


_pg_safety_guards.guard_against_populated_db(_TEST_DB_URL)
_pg_safety_guards.guard_against_real_data_roots(_TEST_CLAUDE_DIR)
_guard_against_venv_lock_drift()
_USE_PG = _pg_available()

# The SQLite PATHS are already isolated unconditionally by
# _redirect_real_data_roots() above. Only the backend SELECTION is decided
# here: with no PG to talk to, the suite must run on SQLite. When PG is
# reachable the caller's choice of backend stands — an exported
# CORTEX_MEMORY_STORE_BACKEND=sqlite is honored, and is now isolated too.
if not _USE_PG:
    os.environ["CORTEX_MEMORY_STORE_BACKEND"] = "sqlite"


def _effective_backend() -> str:
    """The store the suite actually writes to — "postgresql" or "sqlite".

    `_USE_PG` answers a different question: "is PostgreSQL reachable". The
    two diverge whenever a developer exports
    `CORTEX_MEMORY_STORE_BACKEND=sqlite` on a machine where PG is also up —
    the suite then writes to SQLite while every `if not _USE_PG:` branch
    treats the run as PostgreSQL, so the between-test SQLite purge never
    runs and rows leak from one test into the next.

    Resolution mirrors `memory_store._construct_store`: an explicit backend
    wins; "auto" (the default) means PostgreSQL when reachable and SQLite
    otherwise. source: mcp_server/infrastructure/memory_store.py:164-214.
    """
    explicit = os.environ.get("CORTEX_MEMORY_STORE_BACKEND", "").strip().lower()
    if explicit in ("sqlite", "postgresql"):
        return explicit
    return "postgresql" if _USE_PG else "sqlite"


_BACKEND = _effective_backend()
_USE_PG_STORE = _BACKEND == "postgresql"

# Reusable gate for tests whose SUBJECT is PgMemoryStore itself — they import
# it inside the test body (often via object.__new__, with no live DB), so they
# need psycopg importable even though they never connect. psycopg ships in the
# optional [postgresql] extra, absent from the SQLite-default install, where
# the import raises ModuleNotFoundError and FAILS the test instead of skipping
# it (#220). This is a narrower question than `_USE_PG` (is a server
# reachable?) and than `_USE_PG_STORE` (which backend did we resolve?): it asks
# only whether the driver can be imported.
requires_psycopg = pytest.mark.skipif(
    importlib.util.find_spec("psycopg") is None,
    reason="psycopg not installed ([postgresql] extra); PgMemoryStore is PG-only",
)


# ── Isolate domain_mapping's dev-root scan from the real filesystem ──────
#
# Without this, a test exercising the full consolidate handler walks the
# real, unrelated (potentially enormous) dev-root trees on a contributor's
# machine via os.walk — see tests_py/_domain_mapping_isolation.py's
# docstring for the full incident history (issue #196).
from tests_py._domain_mapping_isolation import isolate_dev_root_scan  # noqa: E402

isolate_dev_root_scan()


def _get_raw_connection():
    """Get a raw psycopg connection to the test database.

    Gated on REACHABILITY (`_USE_PG`), not on the effective backend. These
    are different questions and conflating them regresses the suite: dozens
    of tests are marked `skipif(not _USE_PG)` and construct `PgMemoryStore()`
    in their own fixture, bypassing backend selection entirely. They run
    whenever PostgreSQL is reachable — including a `CORTEX_MEMORY_STORE_BACKEND
    =sqlite` run — and they depend on this between-test purge. Gating it on
    `_USE_PG_STORE` left their rows in place and broke 15 of them (measured
    2026-07-28, paired control against cc08a16).

    The SQLite purge below is the one that belongs to the effective backend.
    Both can be required in the same run; they are not alternatives.
    """
    if not _USE_PG:
        return None
    try:
        import psycopg

        return psycopg.connect(_TEST_DB_URL, autocommit=True)
    except Exception:
        return None


@pytest.fixture(autouse=True)
def _test_isolation():
    """Clean test database and reset singletons between EVERY test.

    This ensures:
    1. Each test starts with empty tables
    2. Handler singletons reconnect fresh
    3. Works with both PostgreSQL and SQLite backends

    Order matters: clean SQLite BEFORE resetting singletons (the store
    reference is needed for cleanup), then reset so next test gets fresh
    connections.
    """
    # Pre-test: clean with existing connections, then reset
    if not _USE_PG_STORE:
        _clean_sqlite_store()

    conn = _get_raw_connection()
    if conn:
        _clean_all_tables(conn)

    _reset_all_singletons()

    yield

    # Post-test: clean again, then reset
    if not _USE_PG_STORE:
        _clean_sqlite_store()

    _reset_all_singletons()

    if conn:
        try:
            conn.close()
        except Exception:
            pass
