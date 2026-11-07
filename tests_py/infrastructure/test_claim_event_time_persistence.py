"""wiki.claim_events keeps a claim's event time apart from its extraction (#717).

Slice 2 of #717: the ``EventTime`` contract (slice 1, ``shared/wiki_ir.py``)
round-trips through both stores with its kind, each bound's precision and,
when the source stated one, its UTC offset. A row written without an event
time reads back ``unknown``, never a date taken from ``extracted_at``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from mcp_server.handlers.wiki_extract import _claim_to_dict
from mcp_server.infrastructure.pg_store_wiki_claims import (
    get_claims_for_memory,
    insert_claim_events,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.shared.wiki_ir import ClaimEvent, EventTime, EvidenceRef, TimeBound
from tests_py.conftest import _USE_PG

_PLUS_TWO = timezone(timedelta(hours=2))


def _naive(*parts: int) -> datetime:
    return datetime(*parts)  # noqa: DTZ001 — an unstated zone is the case under test


EVENT_TIMES = [
    EventTime(),
    EventTime(
        kind="point", start=TimeBound(value=_naive(1969, 7, 20), precision="day")
    ),
    EventTime(
        kind="interval",
        start=TimeBound(
            value=datetime(2026, 3, 1, 9, 30, tzinfo=_PLUS_TWO), precision="minute"
        ),
        end=TimeBound(
            value=datetime(2026, 3, 1, 17, 0, tzinfo=_PLUS_TWO), precision="minute"
        ),
    ),
    EventTime(
        kind="interval", end=TimeBound(value=_naive(2025, 1, 1), precision="year")
    ),
]


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path):
    if request.param == "sqlite":
        s = SqliteMemoryStore(str(tmp_path / "memory.db"))
    else:
        if not _USE_PG:
            pytest.skip("PostgreSQL test database not reachable")
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        s = PgMemoryStore()
    yield s
    s._conn.rollback()
    s.close()


def _stored_event_times(store, claims: list[ClaimEvent]) -> list[EventTime]:
    mid = store.insert_memory({"content": "event time #717", "domain": "t717"})
    for c in claims:
        c.memory_id = mid
    insert_claim_events(store._conn, [_claim_to_dict(c) for c in claims])
    rows = get_claims_for_memory(store._conn, mid)
    return [EventTime.model_validate(r["event_time"]) for r in rows]


def test_each_event_time_kind_round_trips_with_precision_and_offset(store):
    claims = [
        ClaimEvent(text=f"claim {i}", event_time=et) for i, et in enumerate(EVENT_TIMES)
    ]
    stored = _stored_event_times(store, claims)
    assert stored == EVENT_TIMES
    offsets = [b.value.utcoffset() for b in (stored[2].start, stored[2].end) if b]
    assert offsets == [timedelta(hours=2), timedelta(hours=2)]
    assert stored[1].start is not None and stored[1].start.value.tzinfo is None


def _columns(row: dict) -> tuple:
    keys = ("session_id", "text", "claim_type", "entity_ids", "evidence_refs")
    return (*(row[k] for k in keys), row["confidence"], row["supersedes"])


def test_the_event_time_column_leaves_every_other_column_in_place(store):
    mid = store.insert_memory({"content": "columns #717", "domain": "t717"})
    [first] = insert_claim_events(store._conn, [{"memory_id": mid, "text": "old"}])
    ref = {"kind": "url", "target": "https://nasa.gov", "context": None}
    claim = {
        "memory_id": mid,
        "session_id": "s-717",
        "text": "x" * 1950,
        "claim_type": "decision",
        "entity_ids": [3, 5],
        "evidence_refs": [ref],
        "confidence": 0.75,
        "supersedes": first,
    }
    insert_claim_events(store._conn, [claim])
    rows = get_claims_for_memory(store._conn, mid)
    assert first == rows[0]["id"]
    assert _columns(rows[0]) == ("", "old", "assertion", [], [], 0.5, None)
    assert _columns(rows[1]) == (
        "s-717",
        "x" * 1900,
        "decision",
        [3, 5],
        [ref],
        0.75,
        first,
    )


def test_a_historical_event_keeps_its_date_beside_a_recent_extraction(store):
    claim = ClaimEvent(
        text="Apollo 11 landed",
        extracted_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
        event_time=EVENT_TIMES[1],
    )
    [stored] = _stored_event_times(store, [claim])
    assert stored.start is not None and stored.start.value == _naive(1969, 7, 20)


def test_a_row_written_without_an_event_time_reads_back_unknown(store):
    mid = store.insert_memory({"content": "no stated date #717", "domain": "t717"})
    insert_claim_events(store._conn, [{"memory_id": mid, "text": "undated claim"}])
    [row] = get_claims_for_memory(store._conn, mid)
    assert EventTime.model_validate(row["event_time"]) == EventTime()


def test_an_older_sqlite_store_gains_the_column_with_existing_rows_unknown(tmp_path):
    path = tmp_path / "older.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE wiki_claim_events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " memory_id INTEGER, session_id TEXT NOT NULL DEFAULT '', text TEXT NOT NULL,"
        " claim_type TEXT NOT NULL DEFAULT 'assertion',"
        " entity_ids JSON NOT NULL DEFAULT '[]',"
        " evidence_refs JSON NOT NULL DEFAULT '[]',"
        " confidence REAL NOT NULL DEFAULT 0.5, embedding BLOB, supersedes INTEGER,"
        " extracted_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "INSERT INTO wiki_claim_events (memory_id, text) VALUES (7, 'old claim')"
    )
    conn.commit()
    conn.close()
    s = SqliteMemoryStore(str(path))
    try:
        [row] = get_claims_for_memory(s._conn, 7)
        assert EventTime.model_validate(row["event_time"]) == EventTime()
    finally:
        s.close()


def test_the_insert_payload_carries_every_claim_field_unchanged():
    claim = ClaimEvent(
        memory_id=41,
        session_id="s-717",
        text="Apollo 11 landed",
        claim_type="observation",
        entity_ids=[3, 5],
        evidence_refs=[
            EvidenceRef(kind="url", target="https://nasa.gov", context="log")
        ],
        confidence=0.8,
        supersedes=9,
        event_time=EVENT_TIMES[1],
    )
    assert _claim_to_dict(claim) == {
        "memory_id": 41,
        "session_id": "s-717",
        "text": "Apollo 11 landed",
        "claim_type": "observation",
        "entity_ids": [3, 5],
        "evidence_refs": [
            {"kind": "url", "target": "https://nasa.gov", "context": "log"}
        ],
        "confidence": 0.8,
        "supersedes": 9,
        "event_time": {
            "kind": "point",
            "start": {"value": "1969-07-20T00:00:00", "precision": "day"},
        },
    }
