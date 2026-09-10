"""Coerce handler results to JSON-native types for the MCP wire.

source: ADR-0652"""

from __future__ import annotations

import datetime as _dt
import logging
import numbers
from typing import Any, SupportsFloat, cast

logger = logging.getLogger(__name__)

# source: ADR-0652


_NO_TOLIST_RESULT = object()


def _decode_bytes(obj: bytes | bytearray) -> str:
    """Decode raw bytes to a JSON-safe string, replacing invalid sequences."""
    # source: ADR-0652

    return obj.decode("utf-8", "replace")


def _coerce_number(obj: numbers.Number) -> float | None:
    """Best-effort ``float`` coercion for a ``numbers.Number`` that is neither
    ``Integral`` nor ``Real`` (i.e. ``Decimal``, PG NUMERIC via psycopg).

    source: ADR-0652
    """
    try:
        # source: ADR-0652

        return float(cast("SupportsFloat", obj))
    except (TypeError, ValueError):
        return None


def _tolist_fallback(obj: Any) -> Any:
    """Recursively convert via a numpy-style ``.tolist()``, or signal failure.

    source: ADR-0652"""
    tolist = getattr(obj, "tolist", None)
    if not callable(tolist):
        return _NO_TOLIST_RESULT
    try:
        return to_json_native(tolist())
    except Exception as exc:  # noqa: BLE001 — source: ADR-0652
        logger.debug("tolist() conversion failed for %r: %s", type(obj), exc)
        return _NO_TOLIST_RESULT


def to_json_native(obj: Any) -> Any:
    """Recursively convert ``obj`` to JSON-serializable, schema-friendly types.

    source: ADR-0652"""
    # str and bool first: bool is a subclass of numbers.Integral, and str
    # is iterable — both must not fall through to the numeric/sequence arms.
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_json_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_json_native(v) for v in obj]
    # Temporal → ISO-8601 string (also matches `format: date-time` schemas).
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray)):
        return _decode_bytes(obj)
    # numbers.Integral/Real cover numpy.int*/float* (both registered).
    if isinstance(obj, numbers.Integral):
        return int(obj)
    if isinstance(obj, numbers.Real):
        return float(obj)
    if isinstance(obj, numbers.Number):
        coerced = _coerce_number(obj)
        if coerced is not None:
            return coerced
    converted = _tolist_fallback(obj)
    if converted is not _NO_TOLIST_RESULT:
        return converted
    # source: ADR-0652

    return str(obj)
