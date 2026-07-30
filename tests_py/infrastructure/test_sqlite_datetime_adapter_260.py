"""Explicit datetime adapter for the SQLite compat layer (issue #260).

`cascade.py::_update_stage_entered` binds a raw `datetime.datetime` object
as a SQL parameter through `PsycopgCompatConnection.execute` — the only
such call site in this codebase (confirmed by an instrumented full-suite
run, see the issue #260 PR description). Before this fix, sqlite3 fell
back to its *implicit* default adapter for that type, which is deprecated
as of Python 3.12 and fired on every affected test
(`tests_py/handlers/test_consolidate.py::test_with_memories`,
`::test_protected_memories_skip_compression`,
`tests_py/integration/test_memory_lifecycle.py::test_store_consolidate_recall`).

Every test in this module reproduces that exact bound-parameter shape and
fails on the pre-fix code (either by the DeprecationWarning firing, or —
for the backward-compat test — by proving the old and new spellings do not
collapse to the same parsed value, which would be the case if the fix had
silently changed the wire format instead of matching the existing one).
"""

from __future__ import annotations

import sqlite3
import warnings
from datetime import datetime, timezone

from mcp_server.infrastructure.sqlite_compat import (
    PsycopgCompatConnection,
    _adapt_datetime_iso,
)


def _compat_conn() -> PsycopgCompatConnection:
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    return PsycopgCompatConnection(raw)


class TestAdaptDatetimeIso:
    """Unit contract for the adapter function itself."""

    def test_returns_plain_isoformat(self):
        value = datetime(2026, 7, 29, 12, 34, 56, 789012, tzinfo=timezone.utc)
        assert _adapt_datetime_iso(value) == value.isoformat()
        assert _adapt_datetime_iso(value) == "2026-07-29T12:34:56.789012+00:00"

    def test_naive_datetime_round_trips_through_isoformat(self):
        """No tzinfo is still a valid `datetime`; the adapter must not raise."""
        value = datetime(2026, 7, 29, 12, 34, 56)  # noqa: DTZ001 — naive-input is the point of this test
        assert _adapt_datetime_iso(value) == "2026-07-29T12:34:56"


class TestNoDeprecationWarningOnBoundDatetime:
    """Reproduces the exact bug: fails on pre-fix code (adapter not
    registered), passes after (explicit adapter takes over before sqlite3's
    default-adapter fallback ever triggers)."""

    def test_connection_execute_with_raw_datetime_param(self):
        conn = _compat_conn()
        conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, ts TEXT)")
        conn.execute("INSERT INTO memories (id) VALUES (1)")

        now = datetime.now(timezone.utc)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # Mirrors cascade.py::_update_stage_entered exactly: UPDATE ...
            # SET <col> = %s with a raw datetime bound, not `.isoformat()`.
            conn.execute("UPDATE memories SET ts = %s WHERE id = %s", (now, 1))

        deprecation_msgs = [
            str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert deprecation_msgs == [], (
            f"expected no DeprecationWarning binding a raw datetime, "
            f"got: {deprecation_msgs}"
        )

        row = conn.execute("SELECT ts FROM memories WHERE id = 1").fetchone()
        assert row["ts"] == now.isoformat()

    def test_cursor_execute_with_raw_datetime_param(self):
        """Same reproduction through the `with conn.cursor() as cur:` path."""
        conn = _compat_conn()
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, ts TEXT)")

        now = datetime.now(timezone.utc)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with conn.cursor() as cur:
                cur.execute("INSERT INTO t (id, ts) VALUES (%s, %s)", (1, now))

        deprecation_msgs = [
            str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert deprecation_msgs == []

        row = conn.execute("SELECT ts FROM t WHERE id = 1").fetchone()
        assert row["ts"] == now.isoformat()

    def test_executemany_with_raw_datetime_params(self):
        """The batch-insert compat path (issue #206) must adapt too."""
        conn = _compat_conn()
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, ts TEXT)")

        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO t (id, ts) VALUES (%s, %s)", [(1, t1), (2, t2)]
                )

        deprecation_msgs = [
            str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert deprecation_msgs == []

        rows = conn.execute("SELECT ts FROM t ORDER BY id").fetchall()
        assert [r["ts"] for r in rows] == [t1.isoformat(), t2.isoformat()]


class TestBackwardCompatibleRead:
    """Acceptance criterion 3: existing SQLite stores keep reading.

    Writes a row in the PRE-CHANGE spelling (the stdlib's old *implicit*
    adapter used `value.isoformat(" ")` — a space separator, confirmed
    empirically against CPython 3.12.12 before this fix was written) via
    raw SQL, alongside a row written through the POST-CHANGE explicit
    adapter, and asserts `datetime.fromisoformat` — the read path every
    consumer in this codebase uses (`decay_cycle.py`, `cascade.py`,
    `consolidation_engine.py`) — parses both to the identical value.
    """

    def test_old_spelling_and_new_spelling_parse_identically(self):
        value = datetime(2026, 7, 29, 12, 34, 56, 789012, tzinfo=timezone.utc)
        old_spelling = value.isoformat(" ")  # what the deprecated adapter wrote
        new_spelling = _adapt_datetime_iso(value)  # what this fix writes

        assert old_spelling != new_spelling  # genuinely different spellings
        assert datetime.fromisoformat(old_spelling) == datetime.fromisoformat(
            new_spelling
        )
        assert datetime.fromisoformat(old_spelling) == value

    def test_pre_fix_row_on_disk_still_reads_correctly(self):
        """A row inserted with the OLD spelling (raw sqlite3, no compat
        layer, simulating data written before this fix shipped) reads back
        identically to one inserted through the NEW explicit-adapter path.
        """
        conn = _compat_conn()
        conn.execute(
            "CREATE TABLE memories (id INTEGER PRIMARY KEY, stage_entered_at TEXT)"
        )

        value = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        old_spelling = value.isoformat(" ")
        conn.execute(
            "INSERT INTO memories (id, stage_entered_at) VALUES (%s, %s)",
            (1, old_spelling),
        )
        conn.execute(
            "INSERT INTO memories (id, stage_entered_at) VALUES (%s, %s)", (2, value)
        )

        rows = {
            r["id"]: r["stage_entered_at"]
            for r in conn.execute(
                "SELECT id, stage_entered_at FROM memories ORDER BY id"
            ).fetchall()
        }
        assert datetime.fromisoformat(rows[1]) == datetime.fromisoformat(rows[2])
        assert datetime.fromisoformat(rows[1]) == value
