"""Per-process throwaway PostgreSQL test-database lifecycle.

Extracted from `tests_py/conftest.py` (issue #276/#287 boy-scout follow-up):
that file was 501 lines, over both the repo's local 300-line cap and the
global 500-line cap (coding-standards.md §4.1), with these functions
accounting for roughly a third of it. Split along the concern boundary that
was already visible in the file's own section comments — no behavior
change, only explicit-parameter functions in place of closures over
conftest.py's module globals (a DI improvement as a side effect, not the
goal: these are independently testable now).

Ordering/behavior preserved exactly: `conftest.py` still creates the
isolated database (if any) before running its data-safety guards, still
drops it in `pytest_sessionfinish`, and every message/exception-swallowing
choice below is unchanged from the code this was extracted from.

Why per-process isolation exists at all
----------------------------------------
ROOT CAUSE (reproduced deterministically 3/3 + 3/3, 2026-07-10): every
worktree/agent used to default to the SAME physical DB (``cortex_test``).
``conftest.py``'s autouse ``_test_isolation`` fixture runs an unconditional
``DELETE FROM <table>`` before/after EVERY test, in EVERY concurrently
running pytest process. Two pytest invocations sharing that DB race:
process A's between-test purge can delete the row process B just stored,
between B's ``remember()`` and its later ``recall()``/``get_memory()``
call. This produced two previously-reported flakes with unrelated
proximate symptoms (``test_store_consolidate_recall``:
``recall_result["count"] == 0``; ``test_memory_count_unchanged_after_validation``:
``store.get_memory() is None``) — neither an intra-suite ordering bug nor
an embeddings-backend issue, both inter-process contention on one shared
table set. Retrying or skipping would hide the race, not fix it (forbidden
anti-pattern). The correct fix is to give each local pytest process its
own throwaway database — CI already gets a fresh service-container DB per
run, and an explicit ``CORTEX_TEST_DATABASE_URL`` override is respected
verbatim (the caller has taken responsibility for isolation).
"""

from __future__ import annotations

import os


def maintenance_url(url: str) -> str:
    """Same host/creds as `url`, database swapped to the `postgres` maintenance DB."""
    base, _, _query = url.partition("?")
    prefix, _, _dbname = base.rpartition("/")
    return f"{prefix}/postgres"


def _orphan_pid(name: str) -> int | None:
    """The pid encoded in a `cortex_test_pw<pid>_<8-hex>` database name, or
    `None` when the name doesn't carry a numeric pid."""
    rest = name[len("cortex_test_pw") :]
    pid_str = rest.split("_", 1)[0]
    return int(pid_str) if pid_str.isdigit() else None


def _pid_is_definitely_dead(pid: int) -> bool:
    """True only when `pid` is confirmed gone. Best-effort, non-fatal: every
    ambiguous case (still alive, owned by another user, any other OS error)
    counts as "alive" — never risk a false-positive drop of a database
    still in use."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except Exception:
        return False  # permission-denied or any other ambiguity — leave it
    else:
        return False  # still alive


def drop_dead_orphaned_databases(conn) -> None:
    """Drop leftover `cortex_test_pw<pid>_<hex>` databases whose owning PID
    is no longer alive.

    A pytest process killed abnormally (SIGTERM/SIGKILL — e.g. a CI job
    cancellation or a shell timeout) never reaches `pytest_sessionfinish`,
    so its throwaway database is never dropped (measured: 1 orphan produced
    by a bash-tool 2-minute timeout during this investigation, 2026-07-10).
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
        pid = _orphan_pid(name)
        if pid is None or not _pid_is_definitely_dead(pid):
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


def create_isolated_test_database(base_url: str) -> tuple[str, str, str] | None:
    """Create a throwaway PG database for this pytest process.

    Returns `(isolated_url, maintenance_url, db_name)` on success, or `None`
    on any failure (unreachable server, no CREATEDB privilege, etc.) so the
    caller falls back to the shared `base_url` — degrading to prior
    (contention-prone but functional) behavior rather than failing the
    whole session.
    """
    try:
        import psycopg

        db_name = f"cortex_test_pw{os.getpid()}_{os.urandom(4).hex()}"
        maint_url = maintenance_url(base_url)
        with psycopg.connect(maint_url, autocommit=True, connect_timeout=3) as conn:
            drop_dead_orphaned_databases(conn)
            conn.execute(f'CREATE DATABASE "{db_name}"')
    except Exception:
        return None
    prefix = base_url.rpartition("/")[0]
    return f"{prefix}/{db_name}", maint_url, db_name


def drop_isolated_database(maint_url: str, db_name: str) -> None:
    """Drop the throwaway per-process database created above, if any.

    Called from `conftest.py`'s `pytest_sessionfinish` hook (which must
    stay a named hook function in conftest.py itself for pytest to find
    it — this is the extracted body, not the hook).
    """
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
