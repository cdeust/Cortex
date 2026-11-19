"""Transcript fingerprint and the relation of a later version. source: ADR-1143"""

import hashlib

import pytest

from mcp_server.infrastructure import transcript_fingerprint as tf


def _fp(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def test_the_fingerprint_is_the_size_and_sha256_of_the_whole_file(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"hello\n")
    assert tf.transcript_fingerprint(str(path)) == _fp(b"hello\n")


def test_a_file_larger_than_one_chunk_is_hashed_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(tf, "_CHUNK_BYTES", 3)
    data = b"0123456789"
    path = tmp_path / "t.jsonl"
    path.write_bytes(data)
    assert tf.transcript_fingerprint(str(path)) == _fp(data)


def test_an_empty_file_has_a_fingerprint(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"")
    assert tf.transcript_fingerprint(str(path)) == _fp(b"")


@pytest.mark.parametrize("value", [None, "", 7, b"/x"])
def test_no_transcript_path_has_no_fingerprint(value):
    assert tf.transcript_fingerprint(value) is None


def test_an_unreadable_transcript_has_no_fingerprint(tmp_path):
    assert tf.transcript_fingerprint(str(tmp_path / "missing.jsonl")) is None
    assert tf.transcript_fingerprint(str(tmp_path)) is None


def test_the_constants_name_the_three_relations():
    assert (tf.REPLAY, tf.APPENDED, tf.REWRITTEN) == ("replay", "appended", "rewritten")


@pytest.mark.parametrize("chunk", [1, 2, 3, 1 << 20])
def test_a_strict_prefix_read_over_several_chunks_is_appended(
    tmp_path, monkeypatch, chunk
):
    monkeypatch.setattr(tf, "_CHUNK_BYTES", chunk)
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"abcdefg")
    assert tf.relation(str(path), _fp(b"abcd"), _fp(b"abcdefg")) == tf.APPENDED


def test_the_same_bytes_are_a_replay(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"abc")
    assert tf.relation(str(path), _fp(b"abc"), _fp(b"abc")) == tf.REPLAY


def test_a_changed_prefix_is_a_rewrite(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"xbcdef")
    assert tf.relation(str(path), _fp(b"abc"), _fp(b"xbcdef")) == tf.REWRITTEN


@pytest.mark.parametrize("current", [b"ab", b"xyz"])
def test_a_file_no_longer_than_the_logged_one_is_a_rewrite(tmp_path, current):
    path = tmp_path / "t.jsonl"
    path.write_bytes(current)
    assert tf.relation(str(path), _fp(b"abc"), _fp(current)) == tf.REWRITTEN


def test_a_file_that_shrank_after_its_fingerprint_is_a_rewrite(tmp_path):
    """The prefix read comes up short: the size check, not the hash, decides."""
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"ab")
    assert tf.relation(str(path), _fp(b"abc"), _fp(b"abcd")) == tf.REWRITTEN


def test_the_prefix_must_match_in_size_and_hash(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"abcd")
    logged = {"bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
    assert tf.relation(str(path), logged, _fp(b"abcd")) == tf.APPENDED
    wrong = {"bytes": 3, "sha256": hashlib.sha256(b"ab").hexdigest()}
    assert tf.relation(str(path), wrong, _fp(b"abcd")) == tf.REWRITTEN


@pytest.mark.parametrize(
    "logged, current",
    [(None, {"bytes": 1, "sha256": "a"}), ({"bytes": 1, "sha256": "a"}, None)],
)
def test_a_missing_fingerprint_cannot_be_compared(logged, current):
    assert tf.relation("/nowhere", logged, current) is None


def test_a_transcript_gone_before_the_prefix_read_cannot_be_compared(tmp_path):
    missing = str(tmp_path / "gone.jsonl")
    assert tf.relation(missing, _fp(b"a"), _fp(b"ab")) is None
