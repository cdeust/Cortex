"""``update_concept`` column allowlist (#197 family 4, S608 sweep).

Before the sweep, ``update_concept`` interpolated arbitrary ``fields``
keys into its ``SET`` clause — the one S608 site whose identifiers did
NOT flow through an in-code allowlist (docs/ASSURANCE-CASE.md §5). These
tests pin the fixed contract: unknown keys are REFUSED before any SQL is
built (refuse-not-escape, same mechanism as
``wiki_view_executor._TABLE_WHITELIST``), known keys still build the
exact allowlisted statement, and the allowlist itself cannot drift from
the ``wiki.concepts`` DDL.

No live PostgreSQL needed: the refusal fires before the connection is
touched, and the happy path is asserted against a mock cursor.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from mcp_server.infrastructure.pg_schema import get_all_ddl
from mcp_server.infrastructure.pg_store_wiki_concepts import (
    _UPDATABLE_COLUMNS,
    update_concept,
)


def _mock_conn() -> MagicMock:
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.rowcount = 1
    return conn


class TestUnknownColumnRefused:
    def test_injection_shaped_key_raises_before_any_sql(self) -> None:
        conn = _mock_conn()
        with pytest.raises(ValueError, match="unknown column"):
            update_concept(conn, 1, {"label = 'x', status": "hijack"})
        conn.cursor.assert_not_called()

    def test_plain_unknown_key_raises_before_any_sql(self) -> None:
        conn = _mock_conn()
        with pytest.raises(ValueError, match="not_a_column"):
            update_concept(conn, 1, {"not_a_column": 1, "label": "ok"})
        conn.cursor.assert_not_called()


class TestAllowlistedUpdateStillWorks:
    def test_known_columns_build_the_exact_statement(self) -> None:
        conn = _mock_conn()
        cursor = conn.cursor.return_value.__enter__.return_value
        assert update_concept(conn, 7, {"label": "L", "status": "promoted"}) is True
        sql, params = cursor.execute.call_args.args
        assert sql == "UPDATE wiki.concepts SET label = %s, status = %s WHERE id = %s"
        assert params == ["L", "promoted", 7]

    def test_empty_fields_is_a_no_op(self) -> None:
        conn = _mock_conn()
        assert update_concept(conn, 7, {}) is False
        conn.cursor.assert_not_called()

    def test_every_typed_set_branch_builds_its_exact_fragment(self) -> None:
        """Pins each special-cased column's SET fragment and parameter
        shape (mutation gate: a mutated cast, a dropped branch, or a
        mis-serialized jsonb payload must fail here)."""
        conn = _mock_conn()
        cursor = conn.cursor.return_value.__enter__.return_value
        fields = {
            "entity_ids": [1, 2],
            "grounding_memory_ids": [3],
            "grounding_claim_ids": [4],
            "properties": {"k": "v"},
            "axial_slots": {"axis": "x"},
            "last_property_at": True,
            "saturation_rate": 0.5,
        }
        assert update_concept(conn, 9, fields) is True
        sql, params = cursor.execute.call_args.args
        assert sql == (
            "UPDATE wiki.concepts SET "
            "entity_ids = %s::int[], "
            "grounding_memory_ids = %s::int[], "
            "grounding_claim_ids = %s::bigint[], "
            "properties = %s::jsonb, "
            "axial_slots = %s::jsonb, "
            "last_property_at = NOW(), "
            "saturation_rate = %s "
            "WHERE id = %s"
        )
        assert params == [
            [1, 2],
            [3],
            [4],
            '{"k": "v"}',
            '{"axis": "x"}',
            0.5,
            9,
        ]

    def test_rowcount_zero_reports_not_updated(self) -> None:
        conn = _mock_conn()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.rowcount = 0
        assert update_concept(conn, 9, {"label": "L"}) is False


class TestAllowlistMatchesDdl:
    def test_every_allowlisted_column_exists_in_the_ddl(self) -> None:
        ddl = "\n;\n".join(get_all_ddl())
        m = re.search(
            r"CREATE TABLE IF NOT EXISTS wiki\.concepts \((.*?)\n\)",
            ddl,
            re.DOTALL,
        )
        assert m, "wiki.concepts DDL not found"
        ddl_columns = {
            line.strip().split()[0]
            for line in m.group(1).splitlines()
            if line.strip() and not line.strip().startswith("--")
        }
        missing = _UPDATABLE_COLUMNS - ddl_columns
        assert not missing, f"allowlist names absent from DDL: {sorted(missing)}"
