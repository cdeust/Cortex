"""Parity roundtrip for injection receipts.

Falsifiable T1 criterion: the persisted receipt items mirror the bound
payload exactly — same memory_ids, same order (rank), same scores.
Runs against the SQLite backend; the PG mixin shares the same contract
(PG parity asserted by the shared insert signature and DDL parity).

source: ADR-0983"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


def _store() -> SqliteMemoryStore:
    return SqliteMemoryStore(db_path=":memory:")


def _payload() -> list[dict]:
    return [
        {"memory_id": 11, "rank": 0, "score": 0.9},
        {"memory_id": 7, "rank": 1, "score": 0.5},
        {"memory_id": 3, "rank": 2, "score": None},
    ]


def test_roundtrip_items_mirror_payload() -> None:
    s = _store()
    rid = s.insert_injection_receipt("recall", _payload())
    rows = s._conn.execute(
        "SELECT memory_id, rank, score FROM injection_receipt_items "
        "WHERE receipt_id = ? ORDER BY rank",
        (rid,),
    ).fetchall()
    assert [(r["memory_id"], r["rank"], r["score"]) for r in rows] == [
        (11, 0, 0.9),
        (7, 1, 0.5),
        (3, 2, None),
    ]


def test_header_records_channel_and_timestamp() -> None:
    s = _store()
    rid = s.insert_injection_receipt("recall", _payload(), session_id="s-1")
    row = s._conn.execute(
        "SELECT session_id, channel, emitted_at FROM injection_receipts WHERE id = ?",
        (rid,),
    ).fetchone()
    assert row["session_id"] == "s-1"
    assert row["channel"] == "recall"
    assert row["emitted_at"]


def test_session_id_nullable() -> None:
    # source: ADR-0983
    s = _store()
    rid = s.insert_injection_receipt("recall", _payload())
    row = s._conn.execute(
        "SELECT session_id FROM injection_receipts WHERE id = ?", (rid,)
    ).fetchone()
    assert row["session_id"] is None


def test_receipts_are_distinct_appends() -> None:
    s = _store()
    a = s.insert_injection_receipt("recall", _payload())
    b = s.insert_injection_receipt("recall", _payload())
    assert a != b
    count = s._conn.execute(
        "SELECT COUNT(*) AS c FROM injection_receipt_items"
    ).fetchone()["c"]
    assert count == 6


def test_empty_items_rejected() -> None:
    s = _store()
    with pytest.raises(ValueError):
        s.insert_injection_receipt("recall", [])


# source: ADR-0983


def _ddl_check_members(ddl: str) -> set[str]:
    """Extract the channel CHECK members from a DDL string."""
    import re

    m = re.search(r"channel IN \(([^)]*)\)", ddl)
    assert m, "channel CHECK constraint not found in DDL"
    return {v.strip().strip("'") for v in m.group(1).split(",")}


def test_channel_enum_parity_sqlite_ddl() -> None:
    from mcp_server.handlers.injection_receipts import INJECTION_CHANNELS
    from mcp_server.infrastructure.sqlite_schema import INJECTION_RECEIPTS_DDL

    assert _ddl_check_members(INJECTION_RECEIPTS_DDL) == set(INJECTION_CHANNELS)


def test_channel_enum_parity_pg_ddl_and_migration() -> None:
    from mcp_server.handlers.injection_receipts import INJECTION_CHANNELS
    from mcp_server.infrastructure import pg_schema

    ddl = pg_schema.SUPPORT_TABLES_DDL
    assert _ddl_check_members(ddl) == set(INJECTION_CHANNELS)
    # The migration that hardens T1-created tables must carry the same enum.
    assert _ddl_check_members(pg_schema.MIGRATIONS_DDL) == set(INJECTION_CHANNELS)


def test_fresh_sqlite_table_rejects_unknown_channel() -> None:
    # Fresh tables carry the CHECK; pre-T2 tables keep free TEXT and rely
    # on the emitter-level validation (documented DDL deviation).
    import sqlite3

    s = _store()
    with pytest.raises(sqlite3.IntegrityError):
        s.insert_injection_receipt("banner", _payload())


def test_all_enum_channels_accepted_by_fresh_sqlite_table() -> None:
    from mcp_server.handlers.injection_receipts import INJECTION_CHANNELS

    s = _store()
    for channel in sorted(INJECTION_CHANNELS):
        assert s.insert_injection_receipt(channel, _payload()) > 0


# source: ADR-0983


def test_fetch_joins_items_to_memories_in_rank_order() -> None:
    s = _store()
    m1 = s.insert_memory({"content": "alpha memory"})
    m2 = s.insert_memory({"content": "beta memory"})
    rid = s.insert_injection_receipt(
        "recall",
        [
            {"memory_id": m2, "rank": 0, "score": 0.9},
            {"memory_id": m1, "rank": 1, "score": None},
        ],
        session_id="s-t3",
    )
    rows = s.fetch_injection_receipts([rid])
    assert [(r["memory_id"], r["rank"], r["content"]) for r in rows] == [
        (m2, 0, "beta memory"),
        (m1, 1, "alpha memory"),
    ]
    assert all(r["receipt_id"] == rid for r in rows)
    assert all(r["session_id"] == "s-t3" for r in rows)
    assert all(r["channel"] == "recall" for r in rows)
    assert all(r["emitted_at"] for r in rows)


def test_fetch_left_join_survives_hard_forgotten_memory() -> None:
    # memory_id carries no FK on purpose: the receipt outlives a
    # hard-forget — the evidence row comes back with m.* all NULL.
    s = _store()
    rid = s.insert_injection_receipt(
        "recall", [{"memory_id": 424242, "rank": 0, "score": 0.4}]
    )
    rows = s.fetch_injection_receipts([rid])
    assert len(rows) == 1
    assert rows[0]["memory_id"] == 424242
    assert rows[0]["memory_row_id"] is None
    assert rows[0]["content"] is None


def test_fetch_orders_by_emitted_at_desc_then_id_desc() -> None:
    s = _store()
    a = s.insert_injection_receipt("recall", _payload()[:1])
    b = s.insert_injection_receipt("recall", _payload()[:1])
    # Same-second inserts: the deterministic tiebreak is id DESC.
    rows = s.fetch_injection_receipts([a, b])
    assert [r["receipt_id"] for r in rows] == [b, a]
    # Age receipt b below a: emitted_at DESC must now dominate the ids.
    s._conn.execute(
        "UPDATE injection_receipts SET emitted_at = '2000-01-01T00:00:00' WHERE id = ?",
        (b,),
    )
    rows = s.fetch_injection_receipts([a, b])
    assert [r["receipt_id"] for r in rows] == [a, b]


def test_fetch_surfaces_superseded_state_never_filters() -> None:
    s = _store()
    m1 = s.insert_memory({"content": "wrong fact"})
    m2 = s.insert_memory({"content": "corrected fact"})
    s._conn.execute("UPDATE memories SET superseded_by_id = ? WHERE id = ?", (m2, m1))
    rid = s.insert_injection_receipt(
        "recall", [{"memory_id": m1, "rank": 0, "score": 0.8}]
    )
    rows = s.fetch_injection_receipts([rid])
    assert len(rows) == 1
    assert rows[0]["superseded_by_id"] == m2


def test_fetch_unknown_and_empty_inputs() -> None:
    s = _store()
    assert s.fetch_injection_receipts([987654]) == []
    assert s.fetch_injection_receipts([]) == []
