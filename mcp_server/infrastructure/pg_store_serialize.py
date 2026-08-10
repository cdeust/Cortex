"""Value-serialization mixin for PgMemoryStore: embedding<->bytes, datetime
normalization, and memory-row normalization for consistent API output.

Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1 cap)
— these are the conversions every read/write path in the other pg_store_*
mixins ultimately funnels through, so they get their own cohesive module
rather than living inside any single caller.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
from pgvector import Vector

from mcp_server.infrastructure.pg_store_host import PgStoreHost


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PgSerializeMixin(PgStoreHost):
    """Embedding<->bytes conversion, datetime normalization, row shaping."""

    # ── Embedding conversion ──────────────────────────────────────────

    @staticmethod
    def _bytes_to_vector(emb: bytes | None) -> np.ndarray | None:
        """Convert float32 bytes blob to numpy array for pgvector."""
        if emb is None:
            return None
        return np.frombuffer(emb, dtype=np.float32)

    @staticmethod
    def _vector_to_bytes(vec: Any) -> bytes | None:
        """Convert pgvector result back to float32 bytes."""
        if vec is None:
            return None
        if isinstance(vec, Vector):
            # pgvector>=0.5.0 psycopg loaders return Vector, not ndarray
            # source: pgvector-python CHANGELOG 0.5.0 (2026-07-06)
            return vec.to_numpy().tobytes()
        return np.asarray(vec, dtype=np.float32).tobytes()

    @staticmethod
    def _now_iso() -> str:
        return _now_iso()

    # ── Row normalization ─────────────────────────────────────────────

    # source: incident 2026-07-11 (garde x3 bench, LongMemEval), RCA in
    # ADR-0054's addendum -- recall_memories() (the WRRF path) returned
    # raw `dict(r)` rows with created_at still a psycopg
    # `datetime.datetime` object, while every other memory-row reader in
    # this class went through _normalize_memory_row and got an ISO
    # string. Both are candidate dicts that can sit in the SAME list
    # (recall_pipeline.spreading_activation_expand appends store.get_memory()
    # rows onto recall_memories()'s output for RRF blending) and reach
    # pg_recall.py::_chronological_rerank's `sorted(..., key=lambda c:
    # c.get("created_at"))` together -- `str < datetime` raises
    # unconditionally. The response schema for `recall`
    # (handlers/recall.py, "created_at": {"type": "string", "format":
    # "date-time"}) has always mandated the string form; recall_memories()
    # was the one path never honoring it. Fixed at the source (both
    # readers now share one normalizer) rather than patched at the sort.
    _DATETIME_FIELDS: tuple[str, ...] = (
        "created_at",
        "ingested_at",
        "last_accessed",
        "last_reconsolidated",
    )

    @staticmethod
    def _isoformat_datetime_fields(
        d: dict[str, Any], fields: tuple[str, ...] = _DATETIME_FIELDS
    ) -> dict[str, Any]:
        """Convert any `datetime.datetime` value in ``fields`` to ISO-8601
        text, in place.

        Precondition: none. Postcondition: for every ``f`` in ``fields``,
        ``d[f]`` is never a ``datetime.datetime`` instance -- either it was
        already something else (str, None, absent), or it is now its
        ``.isoformat()`` string. Every reader of a memory-row dict
        (WRRF candidates, direct get_memory() rows, SA-injected
        candidates) must go through this so a caller can compare/sort
        mixed-origin candidate lists without a type mismatch.
        """
        for field in fields:
            if isinstance(d.get(field), datetime):
                d[field] = d[field].isoformat()
        return d

    def _normalize_memory_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Normalize a memory row for consistent API output.

        Post-A3 the memories table stores ``heat_base``; Python callers
        still read the dict key ``heat``. The normalizer exposes
        ``heat`` as an alias for ``heat_base`` so downstream code does
        not need to know whether the recall path went through
        effective_heat() or a direct row select.
        """
        d = dict(row)
        # A3: expose heat_base as heat for Python callers that expect
        # the pre-A3 dict key. recall_memories() already returns heat
        # (via effective_heat); this handles direct SELECT paths.
        if "heat" not in d and "heat_base" in d:
            d["heat"] = d["heat_base"]
        # Convert embedding back to bytes
        if "embedding" in d and d["embedding"] is not None:
            d["embedding"] = self._vector_to_bytes(d["embedding"])
        # Ensure tags is a list
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        return self._isoformat_datetime_fields(d)
