"""wiki_refine_draft leaves a draft's confidence as its claims set it (issue #578).

The refine handler used to overwrite every refined draft's confidence with a
fixed 0.85, which cleared the curator's approve threshold whatever the
evidence behind the draft's claims. These tests hold the refinement to
wording only, on the SQLite backend through the handlers' own composition
root.

source: ADR-1065
"""

from __future__ import annotations

import pytest

from mcp_server.core.draft_curator import (
    MIN_CONFIDENCE_APPROVE,
    MIN_CONFIDENCE_HOLD,
    evaluate_draft,
)

WEAK_CONFIDENCE = (MIN_CONFIDENCE_HOLD + MIN_CONFIDENCE_APPROVE) / 2
REFINED_LEAD = "pgvector was chosen because HNSW gives sublinear ANN search."


@pytest.fixture()
def sqlite_store(tmp_path, monkeypatch):
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
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    yield store

    reset_shared_store()
    get_memory_settings.cache_clear()


async def _weak_pending_draft(store) -> int:
    """Synthesize drafts, then set one below the approve threshold."""
    from mcp_server.handlers.wiki_extract import handler as extract
    from mcp_server.handlers.wiki_synthesize import handler as synthesize
    from mcp_server.infrastructure.pg_store_wiki import list_drafts, update_draft

    store.insert_memory(
        {
            "content": "We decided to use pgvector because HNSW gives "
            "sublinear ANN search.",
            "domain": "eng",
            "memory_type": "decision",
        }
    )
    await extract({"limit": 50})
    await synthesize({"limit": 50})
    drafts = list_drafts(store._conn, status="pending", limit=1)
    assert drafts, "the synthesizer produced no pending draft to refine"
    draft_id = int(drafts[0]["id"])
    update_draft(store._conn, draft_id, confidence=WEAK_CONFIDENCE)
    store._conn.commit()
    return draft_id


def _refined_memo_confidence(conn, draft_id: int) -> float:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT confidence FROM wiki.memos "
            "WHERE subject_type = %s AND subject_id = %s AND decision = %s",
            ("draft", draft_id, "refined_llm"),
        )
        row = cur.fetchone()
    assert row is not None, "handler_refine recorded no refined_llm memo"
    return float(row["confidence"] if isinstance(row, dict) else row[0])


def _memo_count(conn, draft_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS memo_count FROM wiki.memos "
            "WHERE subject_type = %s AND subject_id = %s",
            ("draft", draft_id),
        )
        row = cur.fetchone()
    return int(row["memo_count"] if isinstance(row, dict) else row[0])


@pytest.mark.asyncio
async def test_a_refine_carrying_no_content_writes_nothing(sqlite_store):
    """Issue #583: a call with only a draft_id refined nothing, yet stamped
    synth_model and left a memo saying a model had refined the draft."""
    from mcp_server.handlers.wiki_refine import handler_refine
    from mcp_server.infrastructure.pg_store_wiki import get_draft

    draft_id = await _weak_pending_draft(sqlite_store)
    before = get_draft(sqlite_store._conn, draft_id)
    memos_before = _memo_count(sqlite_store._conn, draft_id)

    out = await handler_refine({"draft_id": draft_id})

    assert out["updated"] is False
    assert "nothing to refine" in out["error"]
    after = get_draft(sqlite_store._conn, draft_id)
    assert after["synth_model"] == before["synth_model"]
    assert after["lead"] == before["lead"]
    assert _memo_count(sqlite_store._conn, draft_id) == memos_before


@pytest.mark.parametrize(
    ("payload", "named"),
    [
        ({"lead": ""}, "lead"),
        ({"title": "   "}, "title"),
        ({"sections": []}, "sections"),
        ({"frontmatter": {}}, "frontmatter"),
        ({"lead": REFINED_LEAD, "title": ""}, "title"),
    ],
    ids=["blank-lead", "blank-title", "no-sections", "no-frontmatter", "one-of-two"],
)
@pytest.mark.asyncio
async def test_a_refine_carrying_an_empty_value_writes_nothing(
    sqlite_store, payload, named
):
    """Issue #585: `is None` let an empty value through, and writing it blanked
    the field it named while a memo recorded a refinement."""
    from mcp_server.handlers.wiki_refine import handler_refine
    from mcp_server.infrastructure.pg_store_wiki import get_draft

    draft_id = await _weak_pending_draft(sqlite_store)
    before = get_draft(sqlite_store._conn, draft_id)
    memos_before = _memo_count(sqlite_store._conn, draft_id)

    out = await handler_refine({"draft_id": draft_id, **payload})

    assert out["updated"] is False
    assert named in out["error"]
    after = get_draft(sqlite_store._conn, draft_id)
    assert after["lead"] == before["lead"]
    assert after["title"] == before["title"]
    assert after["sections"] == before["sections"]
    assert after["frontmatter"] == before["frontmatter"]
    assert after["synth_model"] == before["synth_model"]
    assert _memo_count(sqlite_store._conn, draft_id) == memos_before


@pytest.mark.asyncio
async def test_refine_keeps_the_draft_confidence(sqlite_store):
    from mcp_server.handlers.wiki_refine import handler_refine
    from mcp_server.infrastructure.pg_store_wiki import get_draft

    draft_id = await _weak_pending_draft(sqlite_store)

    out = await handler_refine({"draft_id": draft_id, "lead": REFINED_LEAD})

    assert out["updated"] is True
    refined = get_draft(sqlite_store._conn, draft_id)
    assert refined["lead"] == REFINED_LEAD
    assert refined["confidence"] == pytest.approx(WEAK_CONFIDENCE)


@pytest.mark.asyncio
async def test_refine_memo_records_the_draft_confidence(sqlite_store):
    from mcp_server.handlers.wiki_refine import handler_refine

    draft_id = await _weak_pending_draft(sqlite_store)

    await handler_refine({"draft_id": draft_id, "lead": REFINED_LEAD})

    memo_confidence = _refined_memo_confidence(sqlite_store._conn, draft_id)
    assert memo_confidence == pytest.approx(WEAK_CONFIDENCE)


@pytest.mark.asyncio
async def test_a_refined_weak_draft_still_misses_the_approve_threshold(sqlite_store):
    from mcp_server.handlers.wiki_refine import handler_refine
    from mcp_server.infrastructure.pg_store_wiki import get_draft

    draft_id = await _weak_pending_draft(sqlite_store)

    await handler_refine({"draft_id": draft_id, "lead": REFINED_LEAD})

    decision = evaluate_draft(get_draft(sqlite_store._conn, draft_id), None)
    assert decision.verdict != "approved"
    assert any("below approve threshold" in r for r in decision.reasons)
