"""#716 acceptance 3: a later version of a logged transcript is exposed.

A transcript that ends a second time under the same stem, with turns
appended or an earlier turn rewritten, replaces its session-log row; the new
row names the version it replaced. A replay keeps the row. source: ADR-1143
"""

import hashlib
import json
from unittest.mock import patch

import pytest

from mcp_server.hooks import session_lifecycle as hook
from mcp_server.hooks.session_log_rows import append_session
from mcp_server.infrastructure import profile_store, session_store
from mcp_server.infrastructure.profile_store import load_profile, save_profile
from mcp_server.infrastructure.session_store import load_session_log


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CORTEX_MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setattr(hook, "METHODOLOGY_DIR", tmp_path / "methodology")
    monkeypatch.setattr(session_store, "SESSION_LOG_PATH", tmp_path / "sessions.json")
    monkeypatch.setattr(profile_store, "DOMAINS_DIR", tmp_path / "domains")
    monkeypatch.setattr(profile_store, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(profile_store, "PROFILES_PATH", tmp_path / "profiles.json")


def _turn(text: str) -> str:
    record = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }
    return json.dumps(record) + "\n"


def _fp(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _end(transcript) -> None:
    event = {"session_id": "s", "project": "rw", "transcript_path": str(transcript)}
    with patch.object(hook, "_spawn_consolidation"):
        hook.process_event(event)


def test_a_rewritten_earlier_turn_replaces_the_row_and_names_the_old_version(tmp_path):
    save_profile("rw", {"projects": ["rw"], "sessionCount": 0})
    transcript = tmp_path / "rollout-a.jsonl"
    first = (_turn("one") + _turn("two")).encode()
    transcript.write_bytes(first)
    _end(transcript)
    logged = load_session_log()["sessions"][0]
    rewritten = (_turn("ONE") + _turn("two")).encode()
    transcript.write_bytes(rewritten)
    _end(transcript)
    rows = load_session_log()["sessions"]
    assert [row["sessionId"] for row in rows] == ["rollout-a"]
    assert rows[0]["transcript"] == _fp(rewritten)
    assert rows[0]["reconciliation"] == {
        "kind": "rewritten",
        "replaced": _fp(first),
        "replacedTimestamp": logged["timestamp"],
    }
    # ADR-1141 is unchanged: the profile is updated once per file.
    assert load_profile("rw")["sessionCount"] == 1


def test_appended_turns_replace_the_row_as_appended(tmp_path):
    transcript = tmp_path / "rollout-a.jsonl"
    first = _turn("one").encode()
    transcript.write_bytes(first)
    _end(transcript)
    grown = first + _turn("two").encode()
    transcript.write_bytes(grown)
    _end(transcript)
    (row,) = load_session_log()["sessions"]
    assert row["turnCount"] == 2
    assert row["transcript"] == _fp(grown)
    assert row["reconciliation"]["kind"] == "appended"
    assert row["reconciliation"]["replaced"] == _fp(first)


def test_a_replay_of_the_same_bytes_keeps_the_row(tmp_path):
    transcript = tmp_path / "rollout-a.jsonl"
    transcript.write_bytes(_turn("one").encode())
    _end(transcript)
    before = load_session_log()["sessions"]
    _end(transcript)
    assert load_session_log()["sessions"] == before
    assert "reconciliation" not in before[0]


def test_a_shorter_file_is_a_rewrite_not_an_append(tmp_path):
    transcript = tmp_path / "rollout-a.jsonl"
    transcript.write_bytes((_turn("one") + _turn("two")).encode())
    _end(transcript)
    transcript.write_bytes(_turn("one").encode())
    _end(transcript)
    (row,) = load_session_log()["sessions"]
    assert row["reconciliation"]["kind"] == "rewritten"


def test_the_replacing_row_moves_to_the_end_of_the_log(tmp_path):
    a, b = tmp_path / "rollout-a.jsonl", tmp_path / "rollout-b.jsonl"
    a.write_bytes(_turn("one").encode())
    b.write_bytes(_turn("other").encode())
    _end(a)
    _end(b)
    a.write_bytes(_turn("changed").encode())
    _end(a)
    rows = load_session_log()["sessions"]
    assert [row["sessionId"] for row in rows] == ["rollout-b", "rollout-a"]


def test_a_row_without_a_fingerprint_is_kept_as_before():
    log = {"sessions": [{"sessionId": "k", "timestamp": "t0"}]}
    entry = {"sessionId": "k", "transcript": {"bytes": 1, "sha256": "x"}}
    assert append_session(log, entry, "/nowhere", 10) is None
    assert log["sessions"] == [{"sessionId": "k", "timestamp": "t0"}]


def test_an_event_without_a_transcript_records_a_null_fingerprint():
    with patch.object(hook, "_spawn_consolidation"):
        hook.process_event({"session_id": "plain", "project": "rw"})
    (row,) = load_session_log()["sessions"]
    assert row["transcript"] is None


def test_a_new_row_returns_none_and_the_log_keeps_its_last_rows():
    log = {"sessions": [{"sessionId": "old"}, {"sessionId": "mid"}]}
    entry = {"sessionId": "new", "transcript": None}
    assert append_session(log, entry, None, 2) is None
    assert [row["sessionId"] for row in log["sessions"]] == ["mid", "new"]


def test_append_session_returns_the_relation_it_applied(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"ab")
    log = {"sessions": [{"sessionId": "k", "transcript": _fp(b"a"), "timestamp": "t0"}]}
    entry = {"sessionId": "k", "transcript": _fp(b"ab")}
    assert append_session(log, entry, str(path), 10) == "appended"
    replay = {"sessionId": "k", "transcript": _fp(b"ab")}
    assert append_session(log, replay, str(path), 10) == "replay"
    assert log["sessions"] == [entry]


def test_an_empty_log_gets_its_first_row():
    log: dict = {}
    entry = {"sessionId": "first", "transcript": None}
    append_session(log, entry, None, 5)
    assert log == {"sessions": [entry]}


def test_the_hook_log_names_a_replacement_and_not_a_replay(tmp_path, capsys):
    transcript = tmp_path / "rollout-a.jsonl"
    transcript.write_bytes(_turn("one").encode())
    _end(transcript)
    _end(transcript)
    assert "replaced" not in capsys.readouterr().err
    transcript.write_bytes(_turn("changed").encode())
    _end(transcript)
    err = capsys.readouterr().err
    assert (
        '[methodology-hook] Session "rollout-a" replaced: transcript rewritten\n' in err
    )
