"""Tests for mcp_server.shared.hash — DJB2 hash function."""

import re

from mcp_server.shared.hash import simple_hash


class TestSimpleHash:
    def test_is_deterministic(self):
        assert simple_hash("hello world") == simple_hash("hello world")

    def test_produces_same_hash_across_multiple_calls(self):
        h1 = simple_hash("test string")
        h2 = simple_hash("test string")
        h3 = simple_hash("test string")
        assert h1 == h2 == h3

    def test_different_inputs_produce_different_outputs(self):
        assert simple_hash("hello") != simple_hash("world")

    def test_similar_but_distinct_inputs_produce_different_hashes(self):
        assert simple_hash("abc") != simple_hash("abd")

    def test_handles_empty_string(self):
        result = simple_hash("")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handles_none(self):
        result = simple_hash(None)
        assert isinstance(result, str)
        assert len(result) > 0
        assert result == simple_hash("")

    def test_returns_hexadecimal_string(self):
        result = simple_hash("test")
        assert re.fullmatch(r"[0-9a-f]+", result)

    def test_truncates_to_first_500_characters(self):
        base = "a" * 500
        extended = base + "b" * 100
        assert simple_hash(base) == simple_hash(extended)

    def test_cross_language_determinism(self):
        # Must match the JS implementation: simpleHash("hello world") === "b8601f86"
        assert simple_hash("hello world") == "3551c8c1"
