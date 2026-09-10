"""Value-serialization mixin for PgMemoryStore: embedding<->bytes, datetime
normalization, and memory-row normalization for consistent API output.

source: ADR-0567"""

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
            # source: ADR-0567
            return vec.to_numpy().tobytes()
        return np.asarray(vec, dtype=np.float32).tobytes()

    @staticmethod
    def _now_iso() -> str:
        return _now_iso()

    # ── Row normalization ─────────────────────────────────────────────

    # source: ADR-0567
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
                ``.isoformat()`` string.

        source: ADR-0567"""
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
        # source: ADR-0567
        if "heat" not in d and "heat_base" in d:
            d["heat"] = d["heat_base"]
        # Convert embedding back to bytes
        if "embedding" in d and d["embedding"] is not None:
            d["embedding"] = self._vector_to_bytes(d["embedding"])
        # source: ADR-0567
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        return self._isoformat_datetime_fields(d)
