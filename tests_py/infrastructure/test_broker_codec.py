"""The broker's value codec and frame parser (ADR-1112 increment 3).

Round trips for every type the store's arguments and results carry, and the
refusals that keep a frame from building arbitrary objects.

source: ADR-1112
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import decimal
import json
import uuid

import numpy as np
import pytest

from mcp_server.infrastructure import broker_protocol as protocol
from mcp_server.infrastructure.broker_codec import CodecError, decode, encode
from mcp_server.infrastructure.schema_versions import SchemaState
from mcp_server.shared.near_dup_calibration import CandidatePair


def _round(value):
    return decode(json.loads(json.dumps(encode(value))))


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        7,
        2.5,
        "texte",
        [1, "a", None],
        (1, (2, 3)),
        {1, 2},
        {7: "int key", 8: [1]},
        {"__t": "a user dict that names the tag"},
        dt.datetime(2026, 10, 21, 9, 30, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 10, 21, 9, 30),  # noqa: DTZ001 — naive values must survive too
        dt.date(2026, 10, 21),
        dt.timedelta(seconds=90.5),
        decimal.Decimal("0.1"),
        uuid.UUID(int=5),
        b"\x00\xffbytes",
        {"nested": {"when": dt.date(2026, 1, 1), "ids": (1, 2)}},
    ],
)
def test_supported_values_round_trip_exactly(value):
    assert _round(value) == value
    assert type(_round(value)) is type(value)


def test_frozenset_arrives_as_a_set_and_bytearray_as_bytes():
    assert _round(frozenset({1})) == {1}
    assert _round(bytearray(b"ab")) == b"ab"


def test_numpy_vectors_keep_dtype_shape_and_values():
    vector = np.arange(384, dtype=np.float32) / 7
    back = _round(vector)
    assert back.dtype == np.float32 and back.shape == (384,)
    assert np.array_equal(back, vector)
    matrix = np.ones((2, 3), dtype=np.float64)
    assert np.array_equal(_round(matrix), matrix)
    assert _round(np.float32(0.5)) == 0.5 and _round(np.int64(3)) == 3


def test_mcp_server_records_round_trip():
    state = SchemaState(fresh=False, version=2, recorded_hash="abc")
    assert _round(state) == state
    pair = CandidatePair(1, 2, 0.93)
    assert _round(pair) == pair and type(_round(pair)) is CandidatePair


@dataclasses.dataclass
class _Foreign:
    x: int


def test_objects_outside_the_closed_set_are_refused():
    with pytest.raises(CodecError):
        encode(object())
    with pytest.raises(CodecError):
        encode(_Foreign(1))  # a dataclass, but not defined under mcp_server


@pytest.mark.parametrize(
    "frame",
    [
        {"__t": "pickle", "v": "x"},
        {"__t": 3},
        {"__t": "rec", "cls": "os:system", "v": {}},
        {"__t": "rec", "cls": "mcp_server.not_imported_module:X", "v": {}},
        {"__t": "rec", "cls": "mcp_server.infrastructure.broker_codec:encode", "v": {}},
        {
            "__t": "rec",
            "cls": "mcp_server.infrastructure.pg_migrations:SchemaState.x",
            "v": {},
        },
    ],
)
def test_a_frame_never_builds_an_arbitrary_object(frame):
    with pytest.raises(CodecError):
        decode(frame)


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        b"[1, 2]",
        b'{"no": "type"}',
        b'{"t": "req", "x": {"__t": "tuple"}}',
        b'{"t": "req", "x": {"__t": "rec", "cls": 5, "v": {}}}',
        b'{"t": "req", "x": {"__t": "dict", "v": [[1]]}}',
        b"\xff\xfe",
        b'{"t": "req", "x": {"__t": "nd", "dtype": "object", "shape": [1],'
        b' "v": "AA=="}}',
        b'{"t": "req", "x": {"__t": "nd", "dtype": "V9", "shape": [1], "v": "AA=="}}',
        b'{"t": "req", "x": {"__t": "b", "v": "not base64!"}}',
        b"[" * 100_000,
    ],
)
def test_malformed_frames_are_protocol_errors(data):
    with pytest.raises(protocol.ProtocolError):
        protocol.loads(data)


def test_oversized_frames_are_refused_before_any_allocation():
    header = protocol.frame(b"x" * 10, 100)[: protocol.HEADER_SIZE]
    assert protocol.frame_length(header, 100) == 10
    huge = (2**32 - 1).to_bytes(4, "big")
    with pytest.raises(protocol.ProtocolError, match="exceeds"):
        protocol.frame_length(huge, protocol.MAX_REQUEST_BYTES)
    with pytest.raises(protocol.ProtocolError, match="exceeds"):
        protocol.frame(b"x" * 101, 100)


def _request(**overrides):
    message = {
        "t": "req",
        "id": 1,
        "kind": "method",
        "name": "get_memory",
        "args": [1],
        "kwargs": {},
        "class": "interactive",
        "deadline": 30.0,
    }
    message.update(overrides)
    return message


@pytest.mark.parametrize(
    "overrides",
    [
        {"t": "hello"},
        {"id": "1"},
        {"kind": "sql"},
        {"name": None},
        {"args": {}},
        {"kwargs": []},
        {"class": "urgent"},
        {"deadline": 0},
        {"deadline": "soon"},
    ],
)
def test_request_shape_is_checked_before_dispatch(overrides):
    with pytest.raises(protocol.ProtocolError):
        protocol.check_request(_request(**overrides))


def test_a_well_formed_request_passes():
    protocol.check_request(_request())
