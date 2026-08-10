"""Coerce handler results to JSON-native types for the MCP wire.

Why this exists
---------------
The MCP SDK builds a tool's ``structuredContent`` by JSON-serializing the
handler's return value and validating it against the declared
``output_schema``. If the value carries a non-JSON-native type the
serializer fails and the SDK emits **no** ``structuredContent`` — the
Claude Code client then rejects the call with "outputSchema defined but
no structured output returned" (reproduced 2026-06-23: ``recall`` returned
memory rows whose ``score`` was ``numpy.float32`` and ``created_at`` a
``datetime``; ``remember`` worked only because its response was already
native).

The wire contract is JSON. The store hands back DB-native types
(``datetime`` from psycopg, ``numpy`` scalars from vector math). This
module enforces the contract at one place — the handler→MCP-SDK boundary
(``tool_error_handler.safe_handler``) — so every tool is covered, not
just the ones touched today (OCP: new tools inherit the guarantee).

``datetime``/``date``/``time`` become ISO-8601 strings, which also
satisfy ``{"type": "string", "format": "date-time"}`` output schemas.

shared/ layer: Python stdlib only. numpy is handled by duck typing
(``numbers`` registration + ``.item()``/``.tolist()``), never imported.
"""

from __future__ import annotations

import datetime as _dt
import logging
import numbers
from typing import Any, SupportsFloat, cast

logger = logging.getLogger(__name__)

# Sentinel distinguishing "tolist() unavailable or failed" from a legitimate
# converted value of None — `to_json_native(None)` is a valid passthrough,
# so `None` itself cannot double as the "no conversion happened" signal.
_NO_TOLIST_RESULT = object()


def _decode_bytes(obj: bytes | bytearray) -> str:
    """Decode raw bytes to a JSON-safe string, replacing invalid sequences."""
    # mutmut_11 (survived, documented equivalent — issue #250 §12.1):
    # codec-name lookup is case-insensitive (codecs.lookup() lowercases
    # before matching an alias), so "utf-8" vs "UTF-8" resolve to the
    # identical codec for every input, not just tested ones — verified
    # 2026-07-29: `codecs.lookup("utf-8") is codecs.lookup("UTF-8")`.
    return obj.decode("utf-8", "replace")


def _coerce_number(obj: numbers.Number) -> float | None:
    """Best-effort ``float`` coercion for a ``numbers.Number`` that is
    neither ``Integral`` nor ``Real`` (i.e. ``Decimal``, PG NUMERIC via
    psycopg). Returns ``None`` — never raises — when coercion is impossible
    (``complex`` has no ``__float__``), so the caller falls through to the
    tolist/str fallback chain instead of the wire payload dropping entirely.
    """
    try:
        # mutmut_17/21/22/23 (survived, documented equivalent — issue #250
        # §12.1): `typing.cast(typ, val)` is `return val` — its first
        # argument is never read at runtime (verified 2026-07-29 via
        # inspect.getsource(typing.cast)), so no test, for any input, can
        # ever observe a change to the type-hint string here. It exists
        # solely for static type checkers.
        return float(cast("SupportsFloat", obj))
    except (TypeError, ValueError):
        return None


def _tolist_fallback(obj: Any) -> Any:
    """Recursively convert via a numpy-style ``.tolist()``, or signal failure.

    Returns ``_NO_TOLIST_RESULT`` when ``obj`` has no callable ``tolist`` or
    when calling it raises — the caller then falls through to ``str(obj)``.
    numpy arrays AND 0-d scalars (incl. ``numpy.bool_``) expose ``tolist()``;
    every numpy scalar has both ``tolist()`` and ``item()``, so a separate
    ``item()`` branch would be unreachable dead code — mutation testing
    (2026-06-23) confirmed all its mutants survived because no input ever
    reaches it past ``tolist()``.
    """
    tolist = getattr(obj, "tolist", None)
    if not callable(tolist):
        return _NO_TOLIST_RESULT
    try:
        return to_json_native(tolist())
    except Exception as exc:  # noqa: BLE001 — stringify fallback below keeps the wire safe
        logger.debug("tolist() conversion failed for %r: %s", type(obj), exc)
        return _NO_TOLIST_RESULT


def to_json_native(obj: Any) -> Any:
    """Recursively convert ``obj`` to JSON-serializable, schema-friendly types.

    Native passthroughs (``None``/``str``/``bool``) are returned unchanged,
    so handlers already returning clean dicts pay only a shallow walk.
    """
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
    # Last resort: stringify so the wire payload stays JSON-safe rather
    # than dropping structuredContent entirely.
    return str(obj)
