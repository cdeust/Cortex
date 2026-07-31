"""Distinguish "PostgreSQL unreachable" from "PostgreSQL reachable but
missing the schema a test needs" (issue #312).

`tests_py/invariants/test_phase2_parity.py`'s original module-level skip
gate checked only bare connectivity (`psycopg.connect(...).close()`
succeeding). A database that is reachable but has never had the schema
migrated — e.g. the per-process throwaway database
`tests_py/_pg_throwaway_db.py` creates for local runs, which is a bare
`CREATE DATABASE` with no tables until some other test in the same session
happens to construct a `PgMemoryStore` first — passes that check and then
dies mid-test with `psycopg.errors.UndefinedTable` instead of skipping,
exactly the class of defect closed for a different test under #219
(ambient-store binding without verifying the store is the right one).

`pg_gate()` below extends the connectivity probe with a schema-presence
check (`SELECT to_regclass(<table>)`, per the issue's own suggested fix)
so "reachable but wrong schema" is treated the same as "unreachable": skip,
with a distinguishing reason, never a hard failure. It does NOT touch how
a test's own assertions fail — a genuine assertion failure inside a test
body still fails; only the module-level connectivity/schema gate changes.
"""

from __future__ import annotations

import warnings


class SchemaSkipWarning(UserWarning):
    """A test module skipped because PostgreSQL is reachable but missing
    required schema.

    Raised via `warnings.warn`, not as an exception: pytest prints a test's
    skip reason only with `-rs`/`-ra` (CI here runs plain `-q`), but always
    prints the warnings summary regardless of verbosity — so a permanently
    -skipping suite surfaces this in CI output instead of silently reading
    as an unrelated, expected "no PostgreSQL" skip.
    """


def pg_gate(
    pg_url: str,
    required_tables: tuple[str, ...],
    *,
    label: str,
) -> tuple[bool, str]:
    """Return `(available, skip_reason)` for a module-level PG skip gate.

    `available` is True only when `pg_url` is reachable AND every name in
    `required_tables` resolves via `to_regclass` — bare reachability is
    not sufficient (issue #312).

    Every table in `required_tables` is checked (not short-circuited on
    the first miss) so the reason names every missing table at once,
    rather than requiring repeated runs to discover them one at a time.
    """
    try:
        import psycopg

        with psycopg.connect(pg_url, autocommit=True, connect_timeout=3) as conn:
            missing = [
                table
                for table in required_tables
                if conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
                is None
            ]
    except Exception:
        return False, f"{label}: PostgreSQL is not reachable at {pg_url!r}"

    if missing:
        reason = (
            f"{label}: PostgreSQL is reachable at {pg_url!r} but missing "
            f"required table(s) {missing!r} — schema not migrated "
            "(issue #312: reachable-but-wrong-schema skips, it does not fail)"
        )
        warnings.warn(SchemaSkipWarning(reason), stacklevel=2)
        return False, reason

    return True, f"{label}: PostgreSQL reachable with required schema present"
