"""Corrections and contradictory dates keep each claim's own event time (#717).

Slice 5 of #717, acceptance criterion 3: "Corrections and contradictory dates
preserve provenance and uncertainty; do not invent a date." The pipeline under
test is the real one, through the handlers' own composition root on the
default SQLite backend: ``wiki_extract`` writes each claim with the date its
sentence states, then ``wiki_resolve`` links the correction to the claim it
replaces and logs the contradictory pair as a conflict candidate.

What must hold afterwards:

- resolution writes ``supersedes`` and memos, and touches no ``event_time``;
- the correction and the claim it supersedes each keep their own date, so the
  older date is still readable, not overwritten by the newer one;
- two claims that state different dates for the same decision both survive
  with their own precision, and the conflict memo names both;
- a claim whose sentence states no date stays ``unknown``: it takes no date
  from its neighbours in the chain and none from ``extracted_at``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from mcp_server.core.claim_event_time import stated_event_time
from mcp_server.shared.wiki_ir import EventTime, TimeBound

FIRST = "We decided to use PostgreSQL as the store on 3 March 2025."
CONTRADICTION = "We decided to use PostgreSQL as the store in March 2024."
CORRECTION = "On 10 June 2026 we switched to SQLite, which replaces PostgreSQL."
UNDATED = "We decided to keep PostgreSQL as the store."
TEXTS = (FIRST, CONTRADICTION, CORRECTION, UNDATED)


def _day(*parts: int) -> datetime:
    return datetime(*parts)  # noqa: DTZ001 — the sentences state no zone


EXPECTED = {
    FIRST: EventTime(
        kind="point", start=TimeBound(value=_day(2025, 3, 3), precision="day")
    ),
    CONTRADICTION: EventTime(
        kind="point", start=TimeBound(value=_day(2024, 3, 1), precision="month")
    ),
    CORRECTION: EventTime(
        kind="point", start=TimeBound(value=_day(2026, 6, 10), precision="day")
    ),
    UNDATED: EventTime(),
}


@pytest.fixture()
def sqlite_store(tmp_path, monkeypatch):
    """Point the whole composition root at a fresh SQLite database."""
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import (
        get_shared_store,
        reset_shared_store,
    )

    db = tmp_path / "memory.db"
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CORTEX_MEMORY_DB_PATH", str(db))
    monkeypatch.setenv("CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(db))
    get_memory_settings.cache_clear()
    reset_shared_store()
    settings = get_memory_settings()
    yield get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    reset_shared_store()
    get_memory_settings.cache_clear()


def _query(store, sql: str, params: tuple = ()) -> list[dict]:
    with store._conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _claims(store) -> dict[str, dict]:
    rows = _query(
        store, "SELECT id, text, supersedes, event_time FROM wiki.claim_events"
    )
    return {r["text"]: r for r in rows}


def _extract_and_resolve(store) -> dict[str, dict]:
    """Remember, extract and resolve each memory in turn, one minute apart.

    ``extracted_at`` defaults to SQLite's ``datetime('now')``, one-second
    resolution, and the resolver only supersedes a prior extracted strictly
    earlier. Memories written in one test run share that second, so each
    extraction is stamped with its own minute, as separate sessions would be.
    Event times are read from the sentences, never from this stamp.
    """
    from mcp_server.handlers import wiki_extract, wiki_resolve

    store_entity = store.insert_entity({"name": "PostgreSQL", "type": "concept"})
    for minute, text in enumerate(TEXTS):
        mid = store.insert_memory({"content": text, "memory_type": "decision"})
        store.insert_memory_entity(mid, store_entity)
        assert (
            asyncio.run(wiki_extract.handler({"memory_id": mid}))["claims_inserted"]
            == 1
        )
        store._conn.execute(
            "UPDATE wiki.claim_events SET extracted_at = %s WHERE memory_id = %s",
            (f"2026-11-07 10:0{minute}:00", mid),
        )
        asyncio.run(wiki_resolve.handler({"memory_id": mid}))
    return _claims(store)


def test_each_sentence_states_the_date_the_scenario_relies_on():
    """Guards the fixture: the extractor reads these dates, not the test."""
    assert {t: stated_event_time(t) for t in TEXTS} == EXPECTED


def test_resolution_keeps_every_claim_s_own_event_time(sqlite_store):
    claims = _extract_and_resolve(sqlite_store)
    stored = {t: EventTime.model_validate(r["event_time"]) for t, r in claims.items()}
    assert stored == EXPECTED


def test_the_correction_supersedes_without_overwriting_the_older_date(sqlite_store):
    claims = _extract_and_resolve(sqlite_store)
    correction = claims[CORRECTION]
    superseded = next(r for r in claims.values() if r["id"] == correction["supersedes"])
    assert superseded["text"] == CONTRADICTION
    older = EventTime.model_validate(superseded["event_time"])
    newer = EventTime.model_validate(correction["event_time"])
    assert (older, newer) == (EXPECTED[CONTRADICTION], EXPECTED[CORRECTION])
    [memo] = _query(
        sqlite_store,
        "SELECT inputs FROM wiki.memos "
        "WHERE decision = 'supersedes' AND subject_id = %s",
        (correction["id"],),
    )
    assert memo["inputs"] == {"superseded_claim_id": superseded["id"]}


def test_contradictory_dates_are_both_kept_and_logged_as_a_conflict(sqlite_store):
    claims = _extract_and_resolve(sqlite_store)
    first, contradiction = claims[FIRST], claims[CONTRADICTION]
    pairs = {
        tuple(sorted((m["subject_id"], m["inputs"]["claim_b_id"])))
        for m in _query(
            sqlite_store,
            "SELECT subject_id, inputs FROM wiki.memos "
            "WHERE decision = 'conflict_candidate'",
        )
    }
    assert tuple(sorted((first["id"], contradiction["id"]))) in pairs
    assert first["supersedes"] is None and contradiction["supersedes"] is None
    assert first["event_time"] != contradiction["event_time"]


def test_an_undated_claim_takes_no_date_from_its_neighbours(sqlite_store):
    claims = _extract_and_resolve(sqlite_store)
    undated = claims[UNDATED]
    assert undated["event_time"] == {"kind": "unknown"}
    assert undated["supersedes"] is None
