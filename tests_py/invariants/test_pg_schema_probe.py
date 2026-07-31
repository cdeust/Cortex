"""Tests for tests_py/invariants/_pg_schema_probe.py (issue #312).

Each test traces to one clause of the probe's contract:
  - unreachable PostgreSQL -> (False, reason naming "not reachable"), no
    warning (that is the ordinary, expected "no PG here" case — warning on
    it would be noise on every SQLite-only run).
  - reachable but missing required table(s) -> (False, reason naming every
    missing table + issue #312), AND a `SchemaSkipWarning` so the condition
    is visible in CI's warnings summary under plain `pytest -q` (which does
    not print skip reasons without `-rs`/`-ra`).
  - reachable with full schema -> (True, reason), no warning.
  - every required table is checked, not just the first miss (a fixture
    with two missing tables must name both).
  - the query is parameter-bound (`%s`, not string-interpolated) and uses
    the exact `to_regclass` shape — pins the SQL text a mutant could
    otherwise weaken into an injection-prone f-string undetected by any
    other test in this file.

Mocking mirrors `tests_py/invariants/test_pg_throwaway_db.py`: a fake
`psycopg` module is injected via `mock.patch.dict(sys.modules, ...)` so no
real network/DB call is made, and `conn.__enter__`/`__exit__` are stubbed
because `pg_gate` uses `with psycopg.connect(...) as conn:`.
"""

from __future__ import annotations

import sys
import types
import unittest.mock as mock
import warnings

import pytest

from tests_py.invariants._pg_schema_probe import SchemaSkipWarning, pg_gate


def _fake_conn(table_oids: dict[str, object]) -> mock.MagicMock:
    """A `conn.execute("SELECT to_regclass(%s)", (table,))` fake whose
    `.fetchone()` returns `(oid,)`, keyed by the table name in `params`."""
    conn = mock.MagicMock()
    conn.__enter__ = mock.Mock(return_value=conn)
    conn.__exit__ = mock.Mock(return_value=False)

    def _execute(query, params):
        assert query == "SELECT to_regclass(%s)"
        (table,) = params
        result = mock.MagicMock()
        result.fetchone.return_value = (table_oids[table],)
        return result

    conn.execute.side_effect = _execute
    return conn


def _fake_psycopg(
    conn: mock.MagicMock | None = None,
    connect_side_effect: Exception | None = None,
) -> types.ModuleType:
    fake = types.ModuleType("psycopg")
    if connect_side_effect is not None:
        fake.connect = mock.Mock(side_effect=connect_side_effect)
    else:
        fake.connect = mock.Mock(return_value=conn)
    return fake


class TestPgGateUnreachable:
    def test_returns_false_with_a_not_reachable_reason(self) -> None:
        fake_pg = _fake_psycopg(connect_side_effect=Exception("connection refused"))
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            available, reason = pg_gate(
                "postgresql://x/nope", ("memories",), label="probe"
            )
        assert available is False
        assert "not reachable" in reason
        assert "postgresql://x/nope" in reason
        assert "probe" in reason

    def test_emits_no_warning(self) -> None:
        """Unreachable PG is the ordinary "no PostgreSQL here" case (e.g. a
        SQLite-only install) — it must stay silent, not warn on every such
        run."""
        fake_pg = _fake_psycopg(connect_side_effect=Exception("connection refused"))
        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            pg_gate("postgresql://x/nope", ("memories",), label="probe")
        assert caught == []

    def test_import_error_is_also_treated_as_unreachable(self) -> None:
        """psycopg absent entirely (SQLite-only install, no [postgresql]
        extra) must degrade to the same "unreachable" outcome, not raise
        ImportError out of the gate."""
        with mock.patch.dict(sys.modules, {"psycopg": None}):
            available, reason = pg_gate(
                "postgresql://x/nope", ("memories",), label="probe"
            )
        assert available is False
        assert "not reachable" in reason


class TestPgGateMissingSchema:
    def test_returns_false_and_names_the_missing_table(self) -> None:
        conn = _fake_conn({"memories": 111, "memory_entities": None})
        fake_pg = _fake_psycopg(conn=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            with pytest.warns(SchemaSkipWarning):
                available, reason = pg_gate(
                    "postgresql://x/db",
                    ("memories", "memory_entities"),
                    label="probe",
                )
        assert available is False
        assert "memory_entities" in reason
        assert "reachable" in reason
        assert "#312" in reason
        assert "probe" in reason

    def test_names_every_missing_table_not_just_the_first(self) -> None:
        conn = _fake_conn({"a": None, "b": 1, "c": None})
        fake_pg = _fake_psycopg(conn=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            with pytest.warns(SchemaSkipWarning):
                available, reason = pg_gate(
                    "postgresql://x/db", ("a", "b", "c"), label="probe"
                )
        assert available is False
        assert "'a'" in reason
        assert "'c'" in reason
        assert "'b'" not in reason
        # Every table was checked (not short-circuited on the first miss).
        assert conn.execute.call_count == 3

    def test_warning_message_matches_the_returned_reason(self) -> None:
        conn = _fake_conn({"memory_entities": None})
        fake_pg = _fake_psycopg(conn=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            with pytest.warns(SchemaSkipWarning) as record:
                _available, reason = pg_gate(
                    "postgresql://x/db", ("memory_entities",), label="probe"
                )
        assert str(record[0].message) == reason

    def test_reason_text_is_exact(self) -> None:
        """A bare `"#312" in reason` substring check does not catch a
        mutant that wraps the literal text in `"XX...XX"` markers or
        upper-cases it wholesale — neither mutation touches the digits in
        "#312", so only an exact match on the full sentence pins the
        literal string mutmut targets."""
        conn = _fake_conn({"memory_entities": None})
        fake_pg = _fake_psycopg(conn=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            with pytest.warns(SchemaSkipWarning):
                _available, reason = pg_gate(
                    "postgresql://x/db", ("memory_entities",), label="probe"
                )
        assert reason == (
            "probe: PostgreSQL is reachable at 'postgresql://x/db' but "
            "missing required table(s) ['memory_entities'] — schema not "
            "migrated (issue #312: reachable-but-wrong-schema skips, it "
            "does not fail)"
        )

    def test_warns_with_stacklevel_2(self) -> None:
        """stacklevel=2 attributes the warning to `pg_gate`'s CALLER (the
        skipping test module's own gate line) rather than to this
        function's own `warnings.warn` call — the entire point of
        surfacing it is to point at the module that is skipping, not at
        this helper. `pytest.warns` does not expose the stacklevel a
        warning was raised with, so `warnings.warn` itself is mocked."""
        conn = _fake_conn({"memory_entities": None})
        fake_pg = _fake_psycopg(conn=conn)
        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch(
                "tests_py.invariants._pg_schema_probe.warnings.warn"
            ) as mock_warn,
        ):
            pg_gate("postgresql://x/db", ("memory_entities",), label="probe")
        mock_warn.assert_called_once()
        _args, kwargs = mock_warn.call_args
        assert kwargs.get("stacklevel") == 2


class TestPgGateFullSchema:
    def test_returns_true_when_every_table_resolves(self) -> None:
        conn = _fake_conn({"memories": 1, "entities": 2, "memory_entities": 3})
        fake_pg = _fake_psycopg(conn=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            available, reason = pg_gate(
                "postgresql://x/db",
                ("memories", "entities", "memory_entities"),
                label="probe",
            )
        assert available is True
        assert "probe" in reason

    def test_emits_no_warning(self) -> None:
        conn = _fake_conn({"memories": 1})
        fake_pg = _fake_psycopg(conn=conn)
        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            pg_gate("postgresql://x/db", ("memories",), label="probe")
        assert caught == []


class TestPgGateConnectionArgs:
    def test_connects_with_exact_reachability_args(self) -> None:
        """Pins `autocommit=True, connect_timeout=3` — a mutant weakening
        either (e.g. `connect_timeout=0`, blocking forever) would pass every
        other test in this file undetected."""
        conn = _fake_conn({"memories": 1})
        fake_pg = _fake_psycopg(conn=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            pg_gate("postgresql://x/db", ("memories",), label="probe")
        fake_pg.connect.assert_called_once_with(
            "postgresql://x/db", autocommit=True, connect_timeout=3
        )

    def test_query_is_parameter_bound_not_string_interpolated(self) -> None:
        """`_fake_conn._execute` already asserts the literal query text on
        every call; this test exists to name the property explicitly so a
        future refactor toward f-string interpolation (a real regression:
        arbitrary table names would then need their own escaping) fails
        here with a clear message rather than only inside a fixture's
        internal assertion."""
        conn = _fake_conn({"memories": 1})
        fake_pg = _fake_psycopg(conn=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            pg_gate("postgresql://x/db", ("memories",), label="probe")
        query, params = conn.execute.call_args.args
        assert query == "SELECT to_regclass(%s)"
        assert params == ("memories",)
