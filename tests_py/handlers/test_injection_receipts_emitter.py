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
    emit_injection_receipt,
)
from mcp_server.shared.injection_markers import (
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
    # source: ADR-0951
    store = _Store()
    with pytest.raises(ValueError):
        emit_injection_receipt(store, _mems(), channel="banner")
    assert store.calls == []


# ── T2 hook channels: the same store path since ADR-1112 increment 2 ─────


@pytest.mark.parametrize("channel", ["session_start", "auto_recall", "agent_briefing"])
def test_hook_channel_receipt_records_channel_session_and_ranks(channel) -> None:
    """Hooks no longer own a connection: they emit through the store like
    the recall handler, with their channel and the transcript's session."""
    store = _Store()
    rid = emit_injection_receipt(
        store,
        [{"memory_id": 11}, {"memory_id": 7}],
        channel=channel,
        session_id="7374abf5-9c12",
    )
    assert rid == 42
    assert store.calls == [
        {
            "channel": channel,
            "items": [
                {"memory_id": 11, "rank": 0, "score": None},
                {"memory_id": 7, "rank": 1, "score": None},
            ],
            "session_id": "7374abf5-9c12",
        }
    ]


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
    # source: ADR-0951
    assert INJECTION_CHANNELS == {
        "recall",
        "session_start",
        "auto_recall",
        "agent_briefing",
    }
