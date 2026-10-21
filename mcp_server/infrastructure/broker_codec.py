"""Values that cross the broker socket: JSON with a closed set of tags.

The store's arguments and results are plain data, with a few types JSON
lacks: timestamps, bytes, numpy vectors (pgvector returns ``ndarray``),
tuples and sets, dicts with non-string keys (``{memory_id: ...}``), and the
small immutable records some operations take or return (dataclasses and
named tuples defined under ``mcp_server``). Each becomes an object with a
``"__t"`` tag. Decoding rebuilds a record only for a dataclass or named
tuple of an ``mcp_server`` module this process has already imported (looked
up in ``sys.modules``: a frame never causes an import); anything else is
refused. No pickle: the socket is authenticated, but a decoder that can
build arbitrary objects would turn any frame into code (ADR-1112, threat
model, tampering).

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import decimal
import sys
import uuid
from typing import Any

# source: ADR-1112 the tag key; a plain dict carrying it is itself tagged
_TAG = "__t"
# source: ADR-1112 a "dict" entry is one [key, value] pair
_PAIR = 2
# source: ADR-1112 records are rebuilt only from these modules
_RECORD_PACKAGE = "mcp_server."
# source: numpy dtype names (str(ndarray.dtype)) of numeric vectors; nothing else
_ARRAY_DTYPES = frozenset(
    {
        "bool",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "float16",
        "float32",
        "float64",
    }
)


class CodecError(ValueError):
    """A value cannot be encoded, or a frame carries an unknown tag."""


def _bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _record(value: Any) -> dict | None:
    cls = type(value)
    if not cls.__module__.startswith(_RECORD_PACKAGE):
        return None
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    elif isinstance(value, tuple) and hasattr(cls, "_fields"):
        fields = dict(zip(cls._fields, value, strict=True))
    else:
        return None
    name = f"{cls.__module__}:{cls.__qualname__}"
    return {_TAG: "rec", "cls": name, "v": encode(fields)}


def _numpy(value: Any) -> Any:
    module = type(value).__module__
    if not module.startswith("numpy"):
        return None
    if hasattr(value, "tobytes") and hasattr(value, "shape") and value.shape != ():
        return {
            _TAG: "nd",
            "dtype": str(value.dtype),
            "shape": list(value.shape),
            "v": _bytes(value.tobytes()),
        }
    return value.item()  # numpy scalar


def encode(value: Any) -> Any:  # noqa: PLR0911 — one branch per supported type
    """A JSON-compatible tree for ``value``; ``CodecError`` if unsupported."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    record = _record(value)
    if record is not None:
        return record
    if isinstance(value, list):
        return [encode(v) for v in value]
    if isinstance(value, tuple):
        return {_TAG: "tuple", "v": [encode(v) for v in value]}
    if isinstance(value, (set, frozenset)):
        return {_TAG: "set", "v": [encode(v) for v in value]}
    if isinstance(value, dict):
        return _encode_dict(value)
    return _encode_scalar(value)


def _encode_dict(value: dict) -> dict:
    if all(isinstance(k, str) for k in value) and _TAG not in value:
        return {k: encode(v) for k, v in value.items()}
    return {_TAG: "dict", "v": [[encode(k), encode(v)] for k, v in value.items()]}


def _encode_scalar(value: Any) -> Any:  # noqa: PLR0911 — one branch per supported type
    if isinstance(value, dt.datetime):
        return {_TAG: "dt", "v": value.isoformat()}
    if isinstance(value, dt.date):
        return {_TAG: "date", "v": value.isoformat()}
    if isinstance(value, dt.timedelta):
        return {_TAG: "td", "v": value.total_seconds()}
    if isinstance(value, decimal.Decimal):
        return {_TAG: "dec", "v": str(value)}
    if isinstance(value, uuid.UUID):
        return {_TAG: "uuid", "v": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {_TAG: "b", "v": _bytes(bytes(value))}
    converted = _numpy(value)
    if converted is not None:
        return converted
    raise CodecError(f"cannot send a {type(value).__name__} through the broker")


def _decode_record(name: str, fields: dict) -> Any:
    module_name, _, qualname = name.partition(":")
    if not module_name.startswith(_RECORD_PACKAGE) or "." in qualname or not qualname:
        raise CodecError(f"refused record class {name!r}")
    module = sys.modules.get(module_name)
    cls = getattr(module, qualname, None) if module is not None else None
    if not isinstance(cls, type) or not (
        dataclasses.is_dataclass(cls)
        or (issubclass(cls, tuple) and hasattr(cls, "_fields"))
    ):
        raise CodecError(f"refused record class {name!r}")
    return cls(**fields)


def _field(item: dict, name: str, kind: type | tuple[type, ...]) -> Any:
    """``item[name]`` if it has the JSON type the tag needs, else refused."""
    value = item.get(name)
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
        raise CodecError(f"tag {item.get(_TAG)!r}: field {name!r} has the wrong type")
    return value


def _decode_text(tag: str, text: str) -> Any:
    try:
        if tag == "dt":
            return dt.datetime.fromisoformat(text)
        if tag == "date":
            return dt.date.fromisoformat(text)
        if tag == "dec":
            return decimal.Decimal(text)
        if tag == "uuid":
            return uuid.UUID(text)
        return base64.b64decode(text, validate=True)
    except (ValueError, decimal.InvalidOperation) as exc:
        raise CodecError(f"tag {tag!r}: {exc}") from exc


def _decode_array(item: dict) -> Any:
    import numpy as np  # noqa: PLC0415 — only frames that carry vectors need it

    name = _field(item, "dtype", str)
    if name not in _ARRAY_DTYPES:
        raise CodecError(f"refused array dtype {name!r}")
    shape = _field(item, "shape", list)
    if not all(
        isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in shape
    ):
        raise CodecError("array shape must be non-negative integers")
    raw = _decode_text("b", _field(item, "v", str))
    return np.frombuffer(raw, dtype=np.dtype(name)).reshape(shape)


def _decode_tagged(tag: str, item: dict) -> Any:  # noqa: PLR0911 — one branch per supported tag
    if tag in ("dt", "date", "dec", "uuid", "b"):
        return _decode_text(tag, _field(item, "v", str))
    if tag == "tuple":
        return tuple(decode(v) for v in _field(item, "v", list))
    if tag == "set":
        return {decode(v) for v in _field(item, "v", list)}
    if tag == "dict":
        pairs = _field(item, "v", list)
        if not all(isinstance(p, list) and len(p) == _PAIR for p in pairs):
            raise CodecError("tag 'dict': every entry must be a [key, value] pair")
        return {decode(k): decode(v) for k, v in pairs}
    if tag == "td":
        seconds = _field(item, "v", (int, float))
        try:
            return dt.timedelta(seconds=seconds)
        except OverflowError as exc:
            raise CodecError(f"tag 'td': {exc}") from exc
    if tag == "nd":
        return _decode_array(item)
    if tag == "rec":
        fields = decode(_field(item, "v", dict))
        return _decode_record(_field(item, "cls", str), fields)
    raise CodecError(f"unknown tag {tag!r}")


def decode(value: Any) -> Any:
    """Inverse of ``encode`` on a parsed JSON tree."""
    if isinstance(value, list):
        return [decode(v) for v in value]
    if isinstance(value, dict):
        tag = value.get(_TAG)
        if tag is None:
            return {k: decode(v) for k, v in value.items()}
        if not isinstance(tag, str):
            raise CodecError("tag must be a string")
        return _decode_tagged(tag, value)
    return value
