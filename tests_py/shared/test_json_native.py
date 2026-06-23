"""Tests for mcp_server.shared.json_native.to_json_native.

Regression guard for the PG-only recall failure (2026-06-23): the PG
store returns ``numpy.float32`` scores and ``datetime`` timestamps where
the SQLite store returns ``float``/``str``. FastMCP can only build
``structuredContent`` from JSON-native values, so a non-native field made
recall fail on PG ("outputSchema defined but no structured output
returned") while passing on SQLite. These tests pin the contract that the
normalizer renders every backend's output JSON-serializable and identical
in type.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import numpy as np

from mcp_server.shared.json_native import to_json_native


def _roundtrips(obj):
    """to_json_native(obj) must be json.dumps-able; return the parsed value."""
    native = to_json_native(obj)
    return json.loads(json.dumps(native)), native


class TestScalars:
    def test_numpy_float32_becomes_python_float(self):
        _, native = _roundtrips({"score": np.float32(0.0026054617)})
        assert isinstance(native["score"], float)
        assert abs(native["score"] - 0.0026054617) < 1e-6

    def test_numpy_int64_becomes_python_int(self):
        _, native = _roundtrips({"id": np.int64(4202320)})
        assert native["id"] == 4202320 and isinstance(native["id"], int)

    def test_numpy_bool_becomes_native(self):
        native = to_json_native(np.bool_(True))
        json.dumps(native)
        assert native is True or native == 1

    def test_decimal_becomes_float(self):
        _, native = _roundtrips({"x": Decimal("1.5")})
        assert isinstance(native["x"], float) and native["x"] == 1.5

    def test_python_natives_pass_through_unchanged(self):
        obj = {"a": 1, "b": 2.0, "c": "x", "d": True, "e": None}
        assert to_json_native(obj) == obj


class TestTemporal:
    def test_aware_datetime_becomes_iso_string(self):
        d = dt.datetime(2026, 6, 10, 13, 19, 31, 178280, tzinfo=dt.timezone.utc)
        native = to_json_native(d)
        assert isinstance(native, str)
        # Round-trips back to the same instant.
        assert dt.datetime.fromisoformat(native) == d

    def test_date_becomes_iso_string(self):
        native = to_json_native(dt.date(2026, 6, 23))
        assert native == "2026-06-23"


class TestContainers:
    def test_nested_memories_list_is_serializable(self):
        payload = {
            "memories": [
                {
                    "score": np.float32(0.5),
                    "created_at": dt.datetime(2026, 6, 10, tzinfo=dt.timezone.utc),
                    "tags": ["a", "b"],
                }
            ],
            "count": 1,
        }
        parsed, _ = _roundtrips(payload)
        assert parsed["count"] == 1
        assert isinstance(parsed["memories"][0]["score"], float)
        assert isinstance(parsed["memories"][0]["created_at"], str)

    def test_set_becomes_list(self):
        native = to_json_native({1, 2, 3})
        assert sorted(native) == [1, 2, 3]

    def test_numpy_array_becomes_list(self):
        _, native = _roundtrips({"vec": np.array([1.0, 2.0], dtype=np.float32)})
        assert native["vec"] == [1.0, 2.0]

    def test_bytes_decode_to_str(self):
        assert to_json_native(b"hi") == "hi"

    def test_invalid_utf8_bytes_replaced_not_raised(self):
        # errors="replace" only matters on INVALID bytes: a strict decode
        # (drop the errors arg) or a bogus errors handler would raise here.
        # This pins the decode contract that ASCII-only inputs cannot.
        native = to_json_native(b"\xff\xfe")
        assert isinstance(native, str)
        json.dumps(native)  # must not raise


class TestFallback:
    def test_unknown_object_stringifies_rather_than_crashing(self):
        class Weird:
            def __repr__(self):
                return "<weird>"

        native = to_json_native({"k": Weird()})
        json.dumps(native)  # must not raise
        assert native["k"] == "<weird>"
