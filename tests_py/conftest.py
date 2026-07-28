"""Global test configuration — isolate tests from every real-data root.

Handler/integration tests hit PostgreSQL when available. When PG is not
available (CI without PG, sandboxed environments), falls back to SQLite
with per-test isolation via temporary DB files.

Isolation has three roots, and ALL THREE are redirected unconditionally
before any `mcp_server` module is imported (see `_redirect_real_data_roots`):
the PostgreSQL URL, the SQLite file, and the `~/.claude` filesystem tree.
"""

import asyncio
import importlib
import os
import sys
import tempfile

import pytest

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
    methodology = os.path.join(_TEST_CLAUDE_DIR, "methodology")
    os.makedirs(methodology, exist_ok=True)
    sqlite_path = os.path.join(methodology, "memory.db")
    # Handlers read the deprecated DB_PATH; the store reads
    # SQLITE_FALLBACK_PATH. Both must point at the throwaway file or the
    # unset one falls back to the (now redirected, but explicit is better)
    # default. source: memory_config.py:48-49.
    os.environ["CORTEX_MEMORY_DB_PATH"] = sqlite_path
    os.environ["CORTEX_MEMORY_SQLITE_FALLBACK_PATH"] = sqlite_path
    return sqlite_path


_ISOLATED_SQLITE_PATH = _redirect_real_data_roots()

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
_CORTEX_TEST_ISOLATE_DB = os.environ.get("CORTEX_TEST_ISOLATE_DB", "1") not in (
    "0",
    "false",
    "False",
)
_OWNED_ISOLATED_DB: tuple[str, str] | None = None  # (maintenance_url, db_name)


def _maintenance_url(url: str) -> str:
    """Same host/creds as `url`, database swapped to the `postgres` maintenance DB."""
    base, _, _query = url.partition("?")
    prefix, _, _dbname = base.rpartition("/")
    return f"{prefix}/postgres"


def _drop_dead_orphaned_databases(conn) -> None:
    """Drop leftover `cortex_test_pw<pid>_<hex>` databases whose owning PID
    is no longer alive.

    A pytest process killed abnormally (SIGTERM/SIGKILL — e.g. a CI job
    cancellation or a shell timeout) never reaches `pytest_sessionfinish`,
    so its throwaway database is never dropped (measured: 1 orphan produced
    by a bash-tool 2-minute timeout during this investigation, 2026-07-10).
    Best-effort, non-fatal: an unreachable/ambiguous entry is left alone
    rather than risking a false-positive drop of a database still in use.
    """
    try:
        rows = conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'cortex_test_pw%';"
        ).fetchall()
    except Exception:
        return
    for row in rows:
        name = row[0] if isinstance(row, tuple) else row.get("datname")
        if not name:
            continue
        # Format: cortex_test_pw<pid>_<8-hex>
        rest = name[len("cortex_test_pw") :]
        pid_str = rest.split("_", 1)[0]
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        try:
            os.kill(pid, 0)
            continue  # process still alive — not an orphan
        except ProcessLookupError:
            pass
        except PermissionError:
            continue  # alive but owned by another user — leave it
        except Exception:
            continue
        try:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        except Exception:
            pass


def _create_isolated_test_database(base_url: str) -> str | None:
    """Create a throwaway PG database for this pytest process; return its URL.

    Returns None on any failure (unreachable server, no CREATEDB privilege,
    etc.) so the caller falls back to the shared `base_url` — degrading to
    prior (contention-prone but functional) behavior rather than failing the
    whole session.
    """
    try:
        import psycopg

        db_name = f"cortex_test_pw{os.getpid()}_{os.urandom(4).hex()}"
        maint_url = _maintenance_url(base_url)
        with psycopg.connect(maint_url, autocommit=True, connect_timeout=3) as conn:
            _drop_dead_orphaned_databases(conn)
            conn.execute(f'CREATE DATABASE "{db_name}"')
    except Exception:
        return None
    global _OWNED_ISOLATED_DB
    _OWNED_ISOLATED_DB = (maint_url, db_name)
    prefix = base_url.rpartition("/")[0]
    return f"{prefix}/{db_name}"


if not _IS_CI and _CORTEX_TEST_ISOLATE_DB and not _EXPLICIT_TEST_DB_URL:
    _isolated_url = _create_isolated_test_database(_TEST_DB_URL)
    if _isolated_url is not None:
        _TEST_DB_URL = _isolated_url

os.environ["DATABASE_URL"] = _TEST_DB_URL


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """Drop the throwaway per-process database created above, if any."""
    if _OWNED_ISOLATED_DB is None:
        return
    maint_url, db_name = _OWNED_ISOLATED_DB
    try:
        import psycopg

        with psycopg.connect(maint_url, autocommit=True, connect_timeout=3) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    except Exception:
        pass


def _looks_like_test_db(url: str) -> bool:
    """True when the database NAME declares itself a test/bench database."""
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    return name.endswith("_test") or name.endswith("_bench") or "_test_" in name


def _guard_against_populated_db() -> None:
    """Refuse to run destructive test isolation against a populated DB.

    INCIDENT 2026-06-10: an agent ran ``DATABASE_URL=<production> CI=true
    pytest`` — the CI branch above trusted the URL verbatim and
    ``_clean_all_tables`` deleted 537,396 production memories (plus all
    entities, relationships, and prospective triggers) between tests.

    Two-tier guard, fail-closed:
      * a database whose NAME marks it as a test DB (``*_test`` /
        ``*_bench``) is trusted — local cortex_test and bench DBs;
      * any OTHER name (e.g. the fresh runner-local ``cortex`` that real
        CI creates) must hold ZERO memories at session start. A genuine
        test database is created empty; pre-existing rows mean this is
        somebody's real store. No threshold constant — empty is empty.

    Override (explicit, never default): CORTEX_TEST_ALLOW_POPULATED=1.
    """
    if os.environ.get("CORTEX_TEST_ALLOW_POPULATED") == "1":
        return
    if _looks_like_test_db(_TEST_DB_URL):
        return
    try:
        import psycopg

        with psycopg.connect(_TEST_DB_URL, autocommit=True, connect_timeout=3) as conn:
            row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            count = row[0] if row else 0
    except Exception:
        return  # unreachable/uninitialized DB — the SQLite fallback handles it
    if count > 0:
        import pytest

        pytest.exit(
            f"REFUSING to run: test DB '{_TEST_DB_URL}' is not named like a "
            f"test database and already holds {count} memories. The test "
            "suite DELETEs every table between tests — pointing it at a real "
            "store destroys it (incident 2026-06-10: 537k rows lost). Use a "
            "*_test database, or set CORTEX_TEST_ALLOW_POPULATED=1 if you "
            "really mean it.",
            returncode=2,
        )


def _guard_against_real_data_roots() -> None:
    """Refuse to run if any resolved root still points at real user data.

    `_redirect_real_data_roots` sets the env vars, but the values that
    actually matter are the ones `mcp_server` RESOLVED from them — an import
    that happened too early, or a future edit that moves the redirection
    below the first import, would leave the constants bound to the real
    `~/.claude` while the env vars look correct. This checks the resolved
    values, so it cannot be fooled by a correct-looking environment.

    Fail-closed and unconditional: there is no override. A suite that DELETEs
    every table between tests and rewrites the wiki has no safe way to run
    against a real tree.

    source: issue #219 — the previous isolation was conditional and its
    failure was silent for as long as it took to notice a 0-row store.
    """
    from mcp_server.infrastructure.config import CLAUDE_DIR, WIKI_ROOT
    from mcp_server.infrastructure.memory_config import get_memory_settings

    settings = get_memory_settings()
    real_root = os.path.realpath(os.path.expanduser("~/.claude"))
    isolated = os.path.realpath(_TEST_CLAUDE_DIR)

    offenders = [
        (name, value)
        for name, value in (
            ("CLAUDE_DIR", str(CLAUDE_DIR)),
            ("WIKI_ROOT", str(WIKI_ROOT)),
            ("MemorySettings.DB_PATH", settings.DB_PATH),
            ("MemorySettings.SQLITE_FALLBACK_PATH", settings.SQLITE_FALLBACK_PATH),
        )
        if not os.path.realpath(os.path.expanduser(value)).startswith(isolated)
    ]
    if offenders:
        detail = "\n".join(f"    {name} -> {value}" for name, value in offenders)
        pytest.exit(
            "REFUSING to run: test isolation is not in effect. These roots "
            f"still resolve outside the throwaway tree {isolated}:\n{detail}\n"
            f"(real user root: {real_root}). The suite DELETEs every table "
            "between tests and regenerates wiki dashboards — running it "
            "against a real tree destroys data (issue #219). Ensure "
            "_redirect_real_data_roots() runs before any mcp_server import.",
            returncode=2,
        )


def _pg_available() -> bool:
    """Check if PostgreSQL is reachable."""
    try:
        import psycopg

        conn = psycopg.connect(_TEST_DB_URL, autocommit=True, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


_guard_against_populated_db()
_guard_against_real_data_roots()
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


# ── Isolate domain_mapping's dev-root scan from the real filesystem ──────
#
# ROOT CAUSE (reproduced deterministically while measuring coverage for
# issue #196, 2026-07-27): shared/domain_mapping._build_registry() (used
# transitively by handlers/consolidation/wiki_backlog_pass.py ->
# core/wiki_drift.py's audit_wiki_drift -> _project_source_root ->
# _file_exists_under's os.walk fallback) has NO test override by
# default. _candidate_dev_roots() falls back to $HOME/Developments,
# $HOME/Documents/Developments, $HOME/dev, $HOME/code — real developer
# directories — and (this is the part that defeats a naive fix) is
# ADDITIVE: even with $CORTEX_DEV_ROOT set, every one of those defaults
# that exists on disk is STILL appended as an extra candidate (see
# shared/domain_mapping.py::_candidate_dev_roots — the env var is one
# more candidate, not a replacement). Setting the env var alone does
# NOT isolate the scan. On a machine where one of the defaults exists
# and holds real git repos (any contributor's normal dev machine), any
# test that exercises the full consolidate handler (e.g.
# test_consolidate_stage_exception_does_not_crash_siblings) transitively
# walks those REAL, unrelated, potentially enormous repo trees via
# os.walk — observed killing a `pytest --cov` run at the 300s per-test
# timeout (pyproject.toml's `timeout = 300`). This is invisible in CI
# because none of the candidate dev roots exist on a CI runner
# ($HOME=/home/runner), so _candidate_dev_roots() returns [] there and
# _project_source_root always returns None — CI's isolation is
# accidental, not designed. This plausibly explains the previously
# unexplained "CI stall on 148d5a1... hung >3h... no offender
# identified" this same `timeout` setting was added to catch (see the
# comment on `timeout_method` above): a local run with a populated dev
# root would reproduce this hang with no per-test timeout to bound it.
#
# Fix: replace `_candidate_dev_roots` itself (not just the env var) so
# it always returns an empty list for the whole test session, matching
# the exact isolation pattern tests_py/shared/test_domain_mapping.py
# already uses per-test (monkeypatch `_candidate_dev_roots` directly,
# then `_build_registry.cache_clear()`). Those dedicated tests
# monkeypatch this same attribute again inside their own test body —
# monkeypatch always restores to whatever was in place when the test
# started, so patching it here at collection time (not via the
# `monkeypatch` fixture, which only exists inside a running test) is a
# permanent module-level replacement for the whole session; the
# per-test monkeypatch calls inside test_domain_mapping.py override it
# for the duration of those specific tests and their own
# `_build_registry.cache_clear()` calls put the real cache state back
# in sync afterward.
from mcp_server.shared import domain_mapping as _dm  # noqa: E402

_dm._candidate_dev_roots = lambda: []
_dm._build_registry.cache_clear()


# ── Tables to clean between tests (order matters for FK constraints) ─────

_TABLES_TO_CLEAN = [
    "memory_rules",
    "consolidation_log",
    "memory_archives",
    "relationships",
    "entities",
    "prospective_memories",
    "checkpoints",
    "engram_slots",
    "oscillatory_state",
    # A3 scalar homeostatic factor: mcp_server/handlers/consolidate.py
    # unconditionally runs run_homeostatic_cycle(store, None) on every
    # handler() call, so every real-store handler test writes a factor
    # row here. Without this table in the cleanup list that row survives
    # for the rest of the pytest session and can perturb a later test's
    # query that joins homeostatic_state (fetch_member_stats,
    # fetch_contents-adjacent CTEs) — first found via CI run 29109251545
    # (2026-07-10) leaving factor=0.9409 for domain='' cross-test.
    #
    # The domain='' mislabeling itself (streaming scalar branch always
    # resolving _dominant_domain([]) to '' regardless of which domain
    # triggered scaling) was a separate production correctness bug,
    # fixed 2026-07-10 in homeostatic.py (_streaming_health now
    # accumulates real per-domain counts during the same cursor pass).
    # This cleanup entry stays regardless — general test-isolation
    # hygiene, independent of that fix.
    "homeostatic_state",
    "schemas",
    # Receipts before memories: items cascade from receipts, and the hook
    # subprocess tests (test_auto_recall, test_hook_receipts) emit receipts
    # that would otherwise accumulate across runs.
    "injection_receipt_items",
    "injection_receipts",
    "memories",
]


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


def _clean_all_tables(conn) -> None:
    """Delete all data from test tables (PostgreSQL)."""
    for table in _TABLES_TO_CLEAN:
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:
            pass


# Always the throwaway file from _redirect_real_data_roots() — never a path
# inherited from the developer's environment (issue #219).
_SQLITE_DB_PATH = _ISOLATED_SQLITE_PATH


def _clean_sqlite_via_singleton() -> bool:
    """Clean SQLite tables via an existing handler singleton's connection.

    Returns True if cleanup succeeded (so we don't need a separate connection).
    This avoids 'database is locked' errors from opening a competing connection
    to a WAL-mode SQLite database.

    Uses dynamic discovery over ALL handler modules (pkgutil.iter_modules) so
    that forget, navigate_memory, and any future handler are covered
    automatically.  The prior hardcoded list of 5 modules omitted those two
    handlers, causing the cleanup to fall back to a competing sqlite3.connect()
    whose WAL-mode writes are immediately visible to the handler's still-open
    connection — producing spurious get_memory()==None failures (diagnosed
    2026-06-17, incident test_forget ~30% cold-start flake rate).
    """
    import pkgutil

    import mcp_server.handlers as handlers_pkg

    for _finder, mod_name, _ispkg in pkgutil.iter_modules(handlers_pkg.__path__):
        try:
            mod = importlib.import_module(f"mcp_server.handlers.{mod_name}")
            store = getattr(mod, "_store", None)
            if store is not None and hasattr(store, "_conn"):
                conn = store._conn
                for table in _TABLES_TO_CLEAN:
                    try:
                        conn.execute(f"DELETE FROM {table}")
                    except Exception:
                        pass
                try:
                    conn.execute("DELETE FROM memories_fts")
                except Exception:
                    pass
                # WAL checkpoint: flush pending writes to main DB file so the
                # next sqlite3.connect() fallback (if it fires) sees a clean
                # slate rather than stale WAL pages.
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
                conn.commit()
                return True
        except Exception:
            pass
    return False


def _clean_sqlite_store() -> None:
    """Clean SQLite tables — prefer singleton connection, fallback to direct."""
    # First try using an existing singleton's connection (avoids DB lock)
    if _clean_sqlite_via_singleton():
        return

    if not _SQLITE_DB_PATH or not os.path.exists(_SQLITE_DB_PATH):
        return
    import sqlite3

    try:
        conn = sqlite3.connect(_SQLITE_DB_PATH, timeout=10)
        for table in _TABLES_TO_CLEAN:
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
        try:
            conn.execute("DELETE FROM memories_fts")
        except Exception:
            pass
        # Checkpoint WAL before close so subsequent opens see a clean DB.
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception:
        pass


# Handler module-level caches that hold (a reference to) the shared store or
# its derivatives. Nulling them forces re-fetch from get_shared_store() after
# the shared store is closed; otherwise a handler would hand back a store whose
# psycopg pools are already closed.
_HANDLER_CACHE_ATTRS = ("_store", "_memory_store", "_embeddings", "_memory_available")


def _reset_all_singletons() -> None:
    """Reset the shared store and handler-level caches so the next test
    reconnects fresh.

    The 37 handlers no longer each own a store — they fetch one process-wide
    instance via get_shared_store(), whose two psycopg pools are the only
    connections held. reset_shared_store() closes those pools (fixing the CI
    connection leak that drove live connections past 60 and triggered the
    30-minute batch-pool acquire hangs). We then null every handler cache by
    iterating the handlers package, so the list cannot drift out of date.
    """
    try:
        from mcp_server.infrastructure.memory_store import reset_shared_store

        reset_shared_store()
    except ImportError:
        pass

    import pkgutil

    import mcp_server.handlers as handlers_pkg

    for _finder, mod_name, _ispkg in pkgutil.iter_modules(handlers_pkg.__path__):
        try:
            mod = importlib.import_module(f"mcp_server.handlers.{mod_name}")
        except Exception:
            continue
        for attr in _HANDLER_CACHE_ATTRS:
            if hasattr(mod, attr):
                # All these caches use None as their "recompute me" sentinel
                # (_memory_available starts None = "not yet checked").
                setattr(mod, attr, None)

    try:
        from mcp_server.infrastructure.memory_config import get_memory_settings

        get_memory_settings.cache_clear()
    except ImportError:
        pass


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
