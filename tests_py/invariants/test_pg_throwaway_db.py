"""Tests for tests_py/_pg_throwaway_db.py — per-process throwaway PG database
lifecycle (issue #276/#287 boy-scout follow-up).

Extracted from `tests_py/conftest.py`'s module-level bootstrap, these
functions previously had no dedicated unit coverage of their own — only
whatever the full test-session bootstrap exercised implicitly. This file
closes that gap for the pieces that matter most: which orphan databases get
dropped (a wrong answer here either leaks throwaway databases forever or
drops one still in use), and that database creation/drop always degrade to
`None`/no-op on any failure rather than raising into collection.

Assertions are exact (`assert_called_once_with`, full SQL/message text)
rather than substring checks wherever a call site is otherwise mocked
permissively enough that a wrong argument or a corrupted literal would
still "work" against the fake — e.g. a fake `psycopg.connect` that accepts
any arguments cannot itself catch a real `test_db_url` silently swapped for
`None`; only asserting the exact call can.
"""

from __future__ import annotations

import os
import re
import sys
import types
import unittest.mock as mock

from tests_py import _pg_throwaway_db as throwaway


class TestMaintenanceUrl:
    def test_swaps_the_database_name_for_postgres(self) -> None:
        assert (
            throwaway.maintenance_url("postgresql://host:5432/cortex_test")
            == "postgresql://host:5432/postgres"
        )

    def test_drops_any_query_string(self) -> None:
        assert (
            throwaway.maintenance_url("postgresql://host/cortex_test?sslmode=require")
            == "postgresql://host/postgres"
        )

    def test_query_string_is_removed_before_finding_the_last_slash(self) -> None:
        """A query string containing its own "/" (e.g. a file-path option)
        must not be mistaken for the database-name separator: the "?" split
        has to happen BEFORE the "/" rpartition, not after."""
        assert (
            throwaway.maintenance_url("postgresql://host/cortex_test?options=/tmp/foo")
            == "postgresql://host/postgres"
        )


class TestOrphanPid:
    """`rest.split("_", 1)[0]` — every name this function is ever called
    against (`cortex_test_pw<pid>_<8-lowercase-hex-chars>`, produced by
    `create_isolated_test_database` and matched by the `LIKE
    'cortex_test_pw%'` query `drop_dead_orphaned_databases` runs) has
    EXACTLY ONE "_" in `rest` — the hex suffix is `os.urandom(4).hex()`,
    whose alphabet (0-9a-f) never contains one. With only one separator to
    split on, `split(sep, 1)`, an unbounded `split(sep)`, `split(sep, 2)`,
    and even `rsplit(sep, 1)` all agree, so mutating between them is a
    provable equivalent HERE, not merely untested — scoped to this domain,
    not a claim that `split`/`rsplit` are equivalent in general (a 200k-case
    fuzz over the real `cortex_test_pw<pid>_<hex>` format confirms
    agreement; an unrestricted fuzz allowing extra underscores anywhere
    does NOT agree, which is why this equivalence is domain-scoped rather
    than structural, unlike the `check_venv_lock_parity.py` regex case in
    issue #287's PR discussion)."""

    def test_parses_the_pid_out_of_a_well_formed_name(self) -> None:
        assert throwaway._orphan_pid("cortex_test_pw12345_ab12cd34") == 12345

    def test_returns_none_for_a_non_numeric_suffix(self) -> None:
        assert throwaway._orphan_pid("cortex_test_pw_not_a_pid") is None


class TestPidIsDefinitelyDead:
    def test_calls_os_kill_with_signal_zero_on_the_given_pid(self) -> None:
        """Signal 0 sends no actual signal — it only probes whether the pid
        exists. `os.kill` is mocked here rather than exercised for real
        (even with the correct, harmless signal 0): a mutation to the
        hardcoded signal number would otherwise make an UNMOCKED call to
        this same test send a real, possibly fatal, signal to the pytest
        process itself when run against that mutant (observed: mutating
        `0` to `1`/SIGHUP under mutmut left the run in a "suspicious",
        not cleanly killed-or-survived, state). Asserting the exact call
        pins both arguments at once: a pid swapped for the wrong value, or
        the probe signal changed to a real one, are both caught here."""
        with mock.patch.object(throwaway.os, "kill") as mock_kill:
            assert throwaway._pid_is_definitely_dead(4242) is False
        mock_kill.assert_called_once_with(4242, 0)

    def test_process_lookup_error_means_dead(self) -> None:
        with mock.patch.object(throwaway.os, "kill", side_effect=ProcessLookupError):
            assert throwaway._pid_is_definitely_dead(999999) is True

    def test_permission_error_is_treated_as_alive(self) -> None:
        """Ambiguous cases must never be treated as dead — dropping a
        database another user's live process owns would be a false
        positive the docstring explicitly refuses to risk."""
        with mock.patch.object(throwaway.os, "kill", side_effect=PermissionError):
            assert throwaway._pid_is_definitely_dead(1) is False


class TestDropDeadOrphanedDatabases:
    def _conn(self, rows):
        conn = mock.MagicMock()
        conn.execute.return_value.fetchall.return_value = rows
        return conn

    def test_selects_with_the_exact_query(self) -> None:
        conn = self._conn([])
        throwaway.drop_dead_orphaned_databases(conn)
        conn.execute.assert_called_once_with(
            "SELECT datname FROM pg_database WHERE datname LIKE 'cortex_test_pw%';"
        )

    def test_reads_the_datname_key_from_a_dict_style_row(self) -> None:
        """psycopg can return dict-like rows (row_factory=dict_row) as well
        as tuples; the `row.get("datname")` branch needs its own case,
        not just the tuple-row one the other tests exercise. Reading the
        WRONG key would make `name` fall back to `.get`'s default `None`
        for a real dict that has no such key — falsy either way — so the
        distinguishing observation is a DROP that only happens when the
        correct key is actually read, not merely "does not raise"."""
        conn = self._conn([{"datname": "cortex_test_pw999999_deadbeef"}])
        with mock.patch.object(throwaway, "_pid_is_definitely_dead", return_value=True):
            throwaway.drop_dead_orphaned_databases(conn)
        dropped = " ".join(str(call) for call in conn.execute.call_args_list)
        assert 'DROP DATABASE IF EXISTS "cortex_test_pw999999_deadbeef"' in dropped

    def test_a_row_with_no_name_does_not_stop_processing_the_rest(self) -> None:
        """A row whose name resolves to falsy (e.g. a dict-style row missing
        the "datname" key entirely) must `continue`, never `break` — the
        SAME invariant as `test_a_dead_row_does_not_stop_processing_the_rest`
        but for the guard clause immediately after the name is read, not the
        one after `_orphan_pid`."""
        conn = self._conn(
            [
                {"unrelated_column": "x"},  # no "datname" key -> name is None
                ("cortex_test_pw999999_deadbeef",),  # a genuine, dead orphan
            ]
        )
        with mock.patch.object(throwaway, "_pid_is_definitely_dead", return_value=True):
            throwaway.drop_dead_orphaned_databases(conn)
        dropped = " ".join(str(call) for call in conn.execute.call_args_list)
        assert "cortex_test_pw999999_deadbeef" in dropped

    def test_drops_a_database_whose_owning_pid_is_gone(self) -> None:
        conn = self._conn([("cortex_test_pw999999_deadbeef",)])
        with mock.patch.object(
            throwaway, "_pid_is_definitely_dead", return_value=True
        ) as mock_is_dead:
            throwaway.drop_dead_orphaned_databases(conn)
        mock_is_dead.assert_called_once_with(999999)
        calls = [call.args[0] for call in conn.execute.call_args_list]
        assert (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()"
        ) in calls
        terminate_call = next(
            c
            for c in conn.execute.call_args_list
            if c.args[0].startswith("SELECT pg_terminate_backend")
        )
        assert terminate_call.args[1] == ("cortex_test_pw999999_deadbeef",)
        assert 'DROP DATABASE IF EXISTS "cortex_test_pw999999_deadbeef"' in calls

    def test_leaves_a_database_whose_owning_pid_is_alive(self) -> None:
        conn = self._conn([(f"cortex_test_pw{os.getpid()}_deadbeef",)])
        throwaway.drop_dead_orphaned_databases(conn)
        dropped = " ".join(str(call) for call in conn.execute.call_args_list)
        assert "DROP DATABASE" not in dropped

    def test_a_dead_row_does_not_stop_processing_the_rest(self) -> None:
        """A malformed/skippable row must `continue`, never `break` — one
        bad row anywhere in the result set must not silently stop dropping
        every orphan listed after it."""
        conn = self._conn(
            [
                ("cortex_test_pw_not_a_pid",),  # no numeric pid -> skip
                ("cortex_test_pw999999_deadbeef",),  # a genuine, dead orphan
            ]
        )
        with mock.patch.object(throwaway, "_pid_is_definitely_dead", return_value=True):
            throwaway.drop_dead_orphaned_databases(conn)
        dropped = " ".join(str(call) for call in conn.execute.call_args_list)
        assert "cortex_test_pw999999_deadbeef" in dropped

    def test_a_selection_failure_is_swallowed(self) -> None:
        conn = mock.MagicMock()
        conn.execute.side_effect = Exception("connection reset")
        throwaway.drop_dead_orphaned_databases(conn)  # must not raise


class TestCreateAndDropIsolatedDatabase:
    def _fake_psycopg(self, connect_side_effect=None):
        fake = types.ModuleType("psycopg")
        conn = mock.MagicMock()
        conn.__enter__ = mock.Mock(return_value=conn)
        conn.__exit__ = mock.Mock(return_value=False)
        conn.execute.return_value.fetchall.return_value = []
        if connect_side_effect is not None:
            fake.connect = mock.Mock(side_effect=connect_side_effect)
        else:
            fake.connect = mock.Mock(return_value=conn)
        return fake, conn

    def test_returns_none_when_the_server_is_unreachable(self) -> None:
        fake_pg, _conn = self._fake_psycopg(
            connect_side_effect=Exception("connection refused")
        )
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            assert (
                throwaway.create_isolated_test_database(
                    "postgresql://localhost/cortex_test"
                )
                is None
            )

    def test_connects_to_the_maintenance_db_with_exact_args(self) -> None:
        fake_pg, _conn = self._fake_psycopg()
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            throwaway.create_isolated_test_database(
                "postgresql://localhost/cortex_test"
            )
        fake_pg.connect.assert_called_once_with(
            "postgresql://localhost/postgres", autocommit=True, connect_timeout=3
        )

    def test_reaps_orphans_on_the_same_connection_before_creating(self) -> None:
        fake_pg, conn = self._fake_psycopg()
        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(throwaway, "drop_dead_orphaned_databases") as mock_reap,
        ):
            throwaway.create_isolated_test_database(
                "postgresql://localhost/cortex_test"
            )
        mock_reap.assert_called_once_with(conn)

    def test_returns_the_isolated_url_and_owner_tuple_on_success(self) -> None:
        fake_pg, conn = self._fake_psycopg()
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            result = throwaway.create_isolated_test_database(
                "postgresql://localhost/cortex_test"
            )
        assert result is not None
        isolated_url, maint_url, db_name = result
        assert maint_url == "postgresql://localhost/postgres"
        # cortex_test_pw<pid>_<8 lowercase hex chars> — the exact format
        # _orphan_pid parses back out, and os.urandom(4).hex() is always 8
        # chars (4 bytes * 2 hex digits/byte).
        assert re.fullmatch(r"cortex_test_pw\d+_[0-9a-f]{8}", db_name)
        assert isolated_url == f"postgresql://localhost/{db_name}"
        # conn.execute is also called once by drop_dead_orphaned_databases's
        # own SELECT (asserted separately in TestDropDeadOrphanedDatabases);
        # the CREATE DATABASE is always the LAST call this function makes.
        conn.execute.assert_called_with(f'CREATE DATABASE "{db_name}"')

    def test_drop_isolated_database_swallows_any_failure(self) -> None:
        fake_pg, _conn = self._fake_psycopg(
            connect_side_effect=Exception("connection refused")
        )
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            throwaway.drop_isolated_database(
                "postgresql://x/postgres", "db1"
            )  # no raise

    def test_drop_isolated_database_connects_with_exact_args(self) -> None:
        fake_pg, _conn = self._fake_psycopg()
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            throwaway.drop_isolated_database("postgresql://x/postgres", "db1")
        fake_pg.connect.assert_called_once_with(
            "postgresql://x/postgres", autocommit=True, connect_timeout=3
        )

    def test_drop_isolated_database_terminates_and_drops_with_exact_sql(self) -> None:
        fake_pg, conn = self._fake_psycopg()
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            throwaway.drop_isolated_database("postgresql://x/postgres", "db1")
        terminate_call, drop_call = conn.execute.call_args_list
        assert terminate_call.args[0] == (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()"
        )
        assert terminate_call.args[1] == ("db1",)
        assert drop_call.args[0] == 'DROP DATABASE IF EXISTS "db1"'
