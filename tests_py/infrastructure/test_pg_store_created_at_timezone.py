"""PgMemoryStore's `created_at` normalization — issue #252, PG side.

The SQLite half of this contract is asserted end-to-end against a real store
in `test_sqlite_backend.py::TestCreatedAtTimezoneIsPersisted`. PostgreSQL
cannot be assumed here (the CI-SQLite job has none), so this pins the same
contract at `_build_insert_params`, the pure mapping that decides the bind
parameter — which is where the defect lived: its own `"T" not in raw_created`
pre-test skipped normalization for every string merely CONTAINING a T, and
every US zone abbreviation does.

Both halves must agree: a zone stated on either backend has to yield the same
instant, or the store silently depends on which backend it runs against
(coding-standards §12.3).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mcp_server.infrastructure.pg_store import PgMemoryStore


def _params(created_at: str) -> dict:
    """`_build_insert_params` without a database.

    It touches `self` only for the static `_bytes_to_vector`, so an
    uninitialised instance is enough — and keeps this test runnable in an
    environment with no PostgreSQL at all.
    """
    store = object.__new__(PgMemoryStore)
    return PgMemoryStore._build_insert_params(
        store, {"content": "c", "created_at": created_at}
    )


class TestCreatedAtTimezone:
    def test_abbreviation_becomes_its_rfc5322_offset(self):
        assert _params("8 May 2023 13:56 EST")["created_at"] == (
            "2023-05-08T13:56:00-05:00"
        )

    def test_bound_value_denotes_the_right_instant(self):
        bound = _params("8 May 2023 13:56 EST")["created_at"]
        instant = datetime.fromisoformat(bound).astimezone(timezone.utc)
        assert instant == datetime(2023, 5, 8, 18, 56, tzinfo=timezone.utc)

    def test_unresolvable_zone_is_not_re_anchored(self):
        bound = _params("8 May 2023 13:56 XYZ")["created_at"]
        assert bound == "8 May 2023 13:56 XYZ"
        with pytest.raises(ValueError):
            datetime.fromisoformat(bound)

    def test_iso_input_is_untouched(self):
        raw = "2023-05-08T13:56:00+02:00"
        assert _params(raw)["created_at"] == raw

    def test_zoneless_locomo_shape_is_normalized(self):
        assert _params("1:56 pm on 8 May, 2023")["created_at"] == (
            "2023-05-08T13:56:00"
        )

    def test_heat_clock_anchors_to_the_normalized_value(self):
        """`heat_base_set_at` is derived from the same value, so a zone lost
        here would also skew the decay clock."""
        params = _params("8 May 2023 13:56 EST")
        assert params["heat_base_set_at"] == params["created_at"]


class TestBackendParity:
    """The two stores must map an identical input to an identical value."""

    @pytest.mark.parametrize(
        "raw",
        [
            "8 May 2023 13:56 EST",
            "8 May 2023 13:56 +02:00",
            "1:56 pm on 8 May, 2023",
            "2023-05-08T13:56:00+02:00",
            "8 May 2023",
        ],
    )
    def test_sqlite_and_postgresql_agree(self, raw):
        from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

        store = SqliteMemoryStore(db_path=":memory:")
        try:
            mem_id = store.insert_memory({"content": "parity", "created_at": raw})
            sqlite_value = store.get_memory(mem_id)["created_at"]
        finally:
            store.close()
        assert sqlite_value == _params(raw)["created_at"]
