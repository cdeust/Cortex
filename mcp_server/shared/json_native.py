"""Coerce handler results to JSON-native types for the MCP wire.

Why this exists
---------------
FastMCP 2.x builds a tool's ``structuredContent`` by JSON-serializing the
handler's return value and validating it against the declared
``output_schema``. If the value carries a non-JSON-native type the
serializer fails and FastMCP emits **no** ``structuredContent`` — the
Claude Code client then rejects the call with "outputSchema defined but
no structured output returned" (reproduced 2026-06-23: ``recall`` returned
memory rows whose ``score`` was ``numpy.float32`` and ``created_at`` a
``datetime``; ``remember`` worked only because its response was already
native).

The wire contract is JSON. The store hands back DB-native types
(``datetime`` from psycopg, ``numpy`` scalars from vector math). This
module enforces the contract at one place — the handler→FastMCP boundary
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
from typing import Any

logger = logging.getLogger(__name__)


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
        return obj.decode("utf-8", "replace")
    # numbers.Integral/Real cover numpy.int*/float* (both registered).
    if isinstance(obj, numbers.Integral):
        return int(obj)
    if isinstance(obj, numbers.Real):
        return float(obj)
    if isinstance(obj, numbers.Number):
        # Decimal is a numbers.Number but NOT numbers.Real (PG NUMERIC maps
        # to Decimal via psycopg). complex has no float() → falls through to
        # the str fallback below, which stays JSON-safe.
        try:
            return float(obj)
        except (TypeError, ValueError):
            pass
    # numpy arrays AND 0-d scalars (incl. numpy.bool_) expose tolist(),
    # which returns native python values. Every numpy scalar has both
    # tolist() and item(), so a separate item() branch would be
    # unreachable dead code — mutation testing (2026-06-23) confirmed all
    # its mutants survived because no input ever reaches it past tolist().
    tolist = getattr(obj, "tolist", None)
    if callable(tolist):
        try:
            return to_json_native(tolist())
        except Exception as exc:  # noqa: BLE001 — stringify fallback below keeps the wire safe
            logger.debug("tolist() conversion failed for %r: %s", type(obj), exc)
    # Last resort: stringify so the wire payload stays JSON-safe rather
    # than dropping structuredContent entirely.
    return str(obj)
