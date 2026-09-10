"""Unit tests for the why handler.

Falsifiable T3 criteria at the handler boundary:

* evidence rows replay the store rows verbatim, in store order —
  recorded facts only, nothing recomputed or reordered client-side;
* unknown receipt ids are reported, never silently dropped;
* superseded and hard-forgotten memories are SURFACED with their state,
  never filtered — receipts are historical evidence;
* the response passes through the same measured budget as recall
  (anti-flooding, correction 5) — truncated rows keep their memory_id;
* malformed receipt_ids raise loudly — a bad id list is a caller bug,
  not a degradation mode.

source: ADR-0960"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from mcp_server.core.response_budget import serialized_length
from mcp_server.handlers import why


class _FakeStore:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[list[int]] = []

    def fetch_injection_receipts(self, receipt_ids: list[int]) -> list[dict]:
        self.calls.append(list(receipt_ids))
        return self.rows


def _row(**overrides) -> dict:
    row = {
        "receipt_id": 1,
        "channel": "recall",
        "session_id": None,
        "emitted_at": "2026-07-07T10:00:00+00:00",
        "memory_id": 11,
        "rank": 0,
        "score": 0.9,
        "memory_row_id": 11,
        "content": "alpha",
        "memory_created_at": "2026-07-01T00:00:00+00:00",
        "memory_source": "lesson",
        "memory_domain": "cortex",
        "superseded_by_id": None,
    }
    row.update(overrides)
    if row["memory_row_id"] is None:
        # LEFT JOIN miss: every m.* column reads NULL.
        for key in (
            "content",
            "memory_created_at",
            "memory_source",
            "memory_domain",
            "superseded_by_id",
        ):
            row[key] = None
    return row


def _patch(monkeypatch, rows: list[dict], budget: int = 75_000) -> _FakeStore:
    store = _FakeStore(rows)
    monkeypatch.setattr(why, "get_shared_store", lambda: store)
    monkeypatch.setattr(
        why,
        "get_memory_settings",
        lambda: SimpleNamespace(MAX_RESPONSE_CHARS=budget),
    )
    return store


@pytest.mark.asyncio
async def test_evidence_replays_store_rows_in_store_order(monkeypatch) -> None:
    rows = [
        _row(
            receipt_id=9,
            channel="auto_recall",
            session_id="s-1",
            emitted_at="2026-07-07T11:00:00+00:00",
            memory_id=42,
            rank=0,
            score=None,
            memory_row_id=42,
            content="beta",
        ),
        _row(receipt_id=4, memory_id=11, rank=0),
        _row(
            receipt_id=4,
            memory_id=7,
            rank=1,
            score=0.5,
            memory_row_id=7,
            content="gamma",
        ),
    ]
    _patch(monkeypatch, rows)
    resp = await why.handler({"receipt_ids": [9, 4]})
    assert [e["receipt_id"] for e in resp["evidence"]] == [9, 4, 4]
    assert [e["memory_id"] for e in resp["evidence"]] == [42, 11, 7]
    assert [e["rank"] for e in resp["evidence"]] == [0, 0, 1]
    first = resp["evidence"][0]
    assert first["channel"] == "auto_recall"
    assert first["session_id"] == "s-1"
    assert first["score"] is None
    assert first["content"] == "beta"
    assert first["memory_missing"] is False
    assert resp["count"] == 3
    assert resp["receipts_resolved"] == [4, 9]
    assert resp["receipts_unknown"] == []


@pytest.mark.asyncio
async def test_semantics_is_locked_lexicon(monkeypatch) -> None:
    _patch(monkeypatch, [_row()])
    resp = await why.handler({"receipt_ids": [1]})
    assert resp["semantics"] == "presence-in-context"


@pytest.mark.asyncio
async def test_unknown_ids_reported_not_dropped(monkeypatch) -> None:
    _patch(monkeypatch, [_row(receipt_id=5)])
    resp = await why.handler({"receipt_ids": [5, 9, 2]})
    assert resp["receipts_resolved"] == [5]
    assert resp["receipts_unknown"] == [9, 2]


@pytest.mark.asyncio
async def test_input_ids_deduplicated_order_preserved(monkeypatch) -> None:
    store = _patch(monkeypatch, [])
    await why.handler({"receipt_ids": [7, 3, 7, "3"]})
    assert store.calls == [[7, 3]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [[], None, "7", [True], ["x"], [0], [-2], [1.5]],
)
async def test_malformed_receipt_ids_raise_loudly(monkeypatch, raw) -> None:
    store = _patch(monkeypatch, [_row()])
    with pytest.raises(ValueError):
        await why.handler({"receipt_ids": raw})
    # The contract violation must raise BEFORE any store I/O.
    assert store.calls == []


@pytest.mark.asyncio
async def test_receipt_ids_bounded_envelope(monkeypatch) -> None:
    """> _MAX_RECEIPT_IDS raises before any store I/O (ADR-0045 R2).

    The bound is the SQLite fallback's documented parameter ceiling
    (SQLITE_MAX_VARIABLE_NUMBER default, sqlite.org/limits.html §9) —
    one bound parameter per id on that path.
    """
    store = _patch(monkeypatch, [_row()])
    at_bound = list(range(1, why._MAX_RECEIPT_IDS + 1))
    await why.handler({"receipt_ids": at_bound})
    assert store.calls == [at_bound]
    with pytest.raises(ValueError, match="at most"):
        await why.handler({"receipt_ids": at_bound + [len(at_bound) + 1]})
    assert len(store.calls) == 1


@pytest.mark.asyncio
async def test_receipt_ids_over_int4_rejected_uniformly(monkeypatch) -> None:
    """ids above int4 raise the same ValueError on every backend.

    Receipt ids are SERIAL (int4); the PG path casts ``::int[]`` and
    would leak NumericValueOutOfRange while SQLite (int64) would return
    receipts_unknown — the parse layer rejects first so the degradation
    mode cannot diverge between backends.
    """
    store = _patch(monkeypatch, [_row()])
    with pytest.raises(ValueError, match="int4"):
        await why.handler({"receipt_ids": [why._INT4_MAX + 1]})
    assert store.calls == []
    await why.handler({"receipt_ids": [why._INT4_MAX]})
    assert store.calls == [[why._INT4_MAX]]


@pytest.mark.asyncio
async def test_hard_forgotten_memory_flagged_not_hidden(monkeypatch) -> None:
    _patch(monkeypatch, [_row(memory_row_id=None)])
    resp = await why.handler({"receipt_ids": [1]})
    item = resp["evidence"][0]
    assert item["memory_missing"] is True
    assert item["memory_id"] == 11
    assert "content" not in item
    assert "superseded_by_id" not in item


@pytest.mark.asyncio
async def test_superseded_memory_surfaced_not_filtered(monkeypatch) -> None:
    _patch(monkeypatch, [_row(superseded_by_id=99)])
    resp = await why.handler({"receipt_ids": [1]})
    assert resp["count"] == 1
    assert resp["evidence"][0]["superseded_by_id"] == 99


@pytest.mark.asyncio
async def test_budget_bounds_response_and_keeps_ids(monkeypatch) -> None:
    # Anti-flooding proof (correction 5): a mutant that skips
    # bound_payload ships ~20k chars against a 1.2k budget and fails.
    rows = [
        _row(receipt_id=2, memory_id=21, content="x" * 10_000),
        _row(
            receipt_id=1,
            memory_id=22,
            rank=0,
            score=0.2,
            memory_row_id=22,
            content="y" * 10_000,
        ),
    ]
    budget = 1_200
    _patch(monkeypatch, rows, budget=budget)
    resp = await why.handler({"receipt_ids": [2, 1]})
    assert serialized_length(resp) <= budget
    for item in resp["evidence"]:
        assert item["memory_id"] in (21, 22)
        assert item.get("truncated") is True
    assert resp["count"] == len(resp["evidence"])


@pytest.mark.asyncio
async def test_datetime_values_serialized_iso(monkeypatch) -> None:
    emitted = datetime(2026, 7, 7, 9, 30, 0, tzinfo=timezone.utc)
    created = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    _patch(
        monkeypatch,
        [_row(emitted_at=emitted, memory_created_at=created)],
    )
    resp = await why.handler({"receipt_ids": [1]})
    item = resp["evidence"][0]
    assert item["emitted_at"] == "2026-07-07T09:30:00+00:00"
    assert item["memory_created_at"] == "2026-07-01T00:00:00+00:00"
