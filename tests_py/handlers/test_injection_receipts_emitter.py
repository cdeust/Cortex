"""Tests for the injection-receipt emitters — blame path T1/T2.

The emitters map the BOUND injected payload to receipt items. Named
degradation modes only: no injection → no receipt; store/DB write
failure (I/O) → degrade to None. A payload entry without memory_id or
an unknown channel is an upstream contract violation and must RAISE —
swallowing it would hide a regression as silently-missing receipts.
"""

from __future__ import annotations

import pytest

from mcp_server.handlers.injection_receipts import (
    INJECTION_CHANNELS,
    emit_hook_receipt,
    emit_injection_receipt,
    receipt_marker,
    session_id_from_transcript,
)


class _Store:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def insert_injection_receipt(
        self, channel: str, items: list[dict], session_id: str | None = None
    ) -> int:
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append(
            {"channel": channel, "items": items, "session_id": session_id}
        )
        return 42


def _mems() -> list[dict]:
    return [
        {"memory_id": 11, "score": 0.9, "content": "a"},
        {"memory_id": 7, "score": None, "content": "b"},
    ]


def test_items_mirror_bound_payload() -> None:
    store = _Store()
    rid = emit_injection_receipt(store, _mems())
    assert rid == 42
    assert store.calls[0]["items"] == [
        {"memory_id": 11, "rank": 0, "score": 0.9},
        {"memory_id": 7, "rank": 1, "score": None},
    ]
    assert store.calls[0]["channel"] == "recall"
    assert store.calls[0]["session_id"] is None


def test_empty_payload_emits_nothing() -> None:
    store = _Store()
    assert emit_injection_receipt(store, []) is None
    assert store.calls == []


def test_missing_memory_id_is_a_loud_contract_violation() -> None:
    store = _Store()
    with pytest.raises(KeyError):
        emit_injection_receipt(store, [{"content": "x", "score": 1.0}])
    assert store.calls == []


def test_store_failure_degrades_to_none() -> None:
    assert emit_injection_receipt(_Store(fail=True), _mems()) is None


def test_unknown_channel_is_a_loud_contract_violation() -> None:
    # T2 channel enum hardening (decision 4255039 correction 3): a
    # channel outside the enum is a coding bug, not a degradation mode.
    store = _Store()
    with pytest.raises(ValueError):
        emit_injection_receipt(store, _mems(), channel="banner")
    assert store.calls == []


# ── T2 hook emitter (caller-owned psycopg connection) ────────────────────


class _Conn:
    """Fake psycopg connection capturing the single-statement insert."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.fail = fail
        self.autocommit = True

    def execute(self, sql: str, params: tuple):
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append((sql, params))
        return self

    def fetchone(self) -> dict:
        return {"receipt_id": 57}


def test_hook_receipt_records_channel_session_and_ranks() -> None:
    conn = _Conn()
    rid = emit_hook_receipt(
        conn,
        [{"memory_id": 11}, {"memory_id": 7}],
        channel="session_start",
        session_id="7374abf5-9c12",
    )
    assert rid == 57
    ((_, params),) = conn.calls
    # (session_id, channel, memory_ids, ranks, scores)  # noqa: ERA001
    assert params == ("7374abf5-9c12", "session_start", [11, 7], [0, 1], [None, None])


def test_hook_receipt_empty_payload_emits_nothing() -> None:
    conn = _Conn()
    assert emit_hook_receipt(conn, [], channel="session_start", session_id=None) is None
    assert conn.calls == []


def test_hook_receipt_write_failure_degrades_to_none() -> None:
    # I/O is the only named degradation mode — the hook keeps printing
    # its (marker-less) banner.
    assert (
        emit_hook_receipt(
            _Conn(fail=True),
            [{"memory_id": 1}],
            channel="agent_briefing",
            session_id=None,
        )
        is None
    )


def test_hook_receipt_unknown_channel_raises_before_io() -> None:
    conn = _Conn()
    with pytest.raises(ValueError):
        emit_hook_receipt(
            conn, [{"memory_id": 1}], channel="preemptive", session_id=None
        )
    assert conn.calls == []


def test_hook_receipt_missing_memory_id_raises() -> None:
    conn = _Conn()
    with pytest.raises(KeyError):
        emit_hook_receipt(
            conn, [{"content": "x"}], channel="auto_recall", session_id=None
        )
    assert conn.calls == []


# ── Correction 7: session identity = transcript basename ─────────────────


def test_session_id_is_transcript_stem() -> None:
    # The event's session_id field diverges from the transcript identity
    # across resume/clear chains (148/200 lines on fixture 7374abf5) —
    # the file basename is the stable identity.
    assert (
        session_id_from_transcript("/x/y/7374abf5-9c12-4d18.jsonl")
        == "7374abf5-9c12-4d18"
    )


def test_session_id_none_without_transcript() -> None:
    assert session_id_from_transcript(None) is None
    assert session_id_from_transcript("") is None


def test_session_id_none_for_non_string_boundary_input() -> None:
    # The hook event is external input — a malformed transcript_path must
    # degrade to None, never raise into the hook's primary injection.
    for garbage in (42, 3.14, True, ["a.jsonl"], {"path": "x"}):
        assert session_id_from_transcript(garbage) is None


# ── Correction 2: in-context receipt marker ───────────────────────────────


def test_receipt_marker_format() -> None:
    assert receipt_marker(57) == "⟦rcpt:57⟧"


def test_enum_members_are_the_four_decided_channels() -> None:
    # Decision 4255039 correction 3 fixed the enum at exactly these four.
    assert INJECTION_CHANNELS == {
        "recall",
        "session_start",
        "auto_recall",
        "agent_briefing",
    }
