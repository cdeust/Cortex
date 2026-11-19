"""A synthesised draft keeps each claim's own event time (#717, slice 6).

Decision of 19 November 2026 on #717 (option (a)): the page carries no date of
its own; each section names, per claim, the ``event_time`` its row stores,
``unknown`` included. The pipeline under test is the real one, through the
handlers' composition root on the default SQLite backend: ``wiki_extract``
reads the dates the sentences state, ``wiki_synthesize`` writes the draft.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from mcp_server.shared.wiki_ir import EventTime, Section, TimeBound

POINT = "We decided to use PostgreSQL as the store on 3 March 2025."
INTERVAL = "We decided to freeze the schema from March 2024 to June 2024."
UNDATED = "We decided to keep SQLite as the default backend for plugin installs."
MEMORY = " ".join((POINT, INTERVAL, UNDATED))


def _month(year: int, month: int) -> TimeBound:
    return TimeBound(value=datetime(year, month, 1), precision="month")  # noqa: DTZ001


EXPECTED = {
    POINT: EventTime(
        kind="point",
        start=TimeBound(value=datetime(2025, 3, 3), precision="day"),  # noqa: DTZ001
    ),
    INTERVAL: EventTime(kind="interval", start=_month(2024, 3), end=_month(2024, 6)),
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


def _rows(store, sql: str) -> list[dict]:
    with store._conn.cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def _synthesise(store) -> tuple[dict[int, str], dict]:
    """Extract and synthesise one memory; return claim id → text, and the draft."""
    from mcp_server.handlers import wiki_extract, wiki_synthesize

    mid = store.insert_memory({"content": MEMORY, "memory_type": "decision"})
    assert asyncio.run(wiki_extract.handler({"memory_id": mid}))["claims_inserted"] == 3
    out = asyncio.run(wiki_synthesize.handler({"memory_id": mid}))
    assert out["errors"] == [] and out["drafts_created"] == 1
    claims = {
        r["id"]: r["text"] for r in _rows(store, "SELECT * FROM wiki.claim_events")
    }
    (draft,) = _rows(store, "SELECT sections, frontmatter FROM wiki.drafts")
    return claims, draft


def test_each_sentence_states_the_date_the_scenario_relies_on():
    """Guards the fixture: the extractor reads these dates, not the test."""
    from mcp_server.core.claim_event_time import stated_event_time

    assert {t: stated_event_time(t) for t in EXPECTED} == EXPECTED


def test_every_claim_of_the_draft_keeps_its_own_event_time(sqlite_store):
    claims, draft = _synthesise(sqlite_store)
    sections = [Section.model_validate(s) for s in draft["sections"]]
    carried = {
        claims[cid]: time for s in sections for cid, time in s.event_times.items()
    }
    assert carried == EXPECTED


def test_a_section_names_a_time_for_exactly_the_claims_it_holds(sqlite_store):
    _, draft = _synthesise(sqlite_store)
    for section in (Section.model_validate(s) for s in draft["sections"]):
        assert set(section.event_times) == set(section.claim_ids)


def test_the_draft_carries_no_page_level_event_date(sqlite_store):
    """No date is aggregated from the claims onto the page (no invented date)."""
    _, draft = _synthesise(sqlite_store)
    frontmatter = draft["frontmatter"] or {}
    assert not {"event_time", "date", "start", "end"} & set(frontmatter)


class _TupleCursor:
    """A cursor that returns positional rows, as a psycopg cursor without
    ``dict_row`` does; records the statement it ran."""

    def __init__(self, rows):
        self.rows, self.ran = rows, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.ran.append((sql, params))

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_a_positional_row_carries_its_event_time_as_the_ninth_column():
    from mcp_server.handlers.wiki_synthesize import _claims_for_memory

    stored = {"kind": "unknown"}
    cursor = _TupleCursor([(7, 3, "t", "decision", None, None, 0.5, None, stored)])
    (claim,) = _claims_for_memory(_Conn(cursor), 3)
    assert claim["event_time"] == stored and claim["supersedes"] is None
    ((sql, params),) = cursor.ran
    assert "supersedes, event_time" in sql and params == (3,)


def test_the_payload_stores_each_section_as_json_ready_dicts():
    """The exact shape insert_draft json-dumps: no ``None`` bound, ISO text."""
    from mcp_server.core.draft_synthesizer import synthesize_draft
    from mcp_server.handlers.wiki_synthesize import _draft_to_payload

    stated = EXPECTED[POINT].model_dump(mode="json", exclude_none=True)
    claim = {"id": 5, "text": POINT, "claim_type": "decision", "event_time": stated}
    draft, _ = synthesize_draft([claim], kind="adr", memory_id=1)
    decision = next(
        s for s in _draft_to_payload(draft)["sections"] if s["heading"] == "Decision"
    )
    assert decision == {
        "heading": "Decision",
        "body": POINT,
        "claim_ids": [5],
        "event_times": {  # JSON object keys are text; Section reads them back
            "5": {
                "kind": "point",
                "start": {"value": "2025-03-03T00:00:00", "precision": "day"},
            }
        },
    }
