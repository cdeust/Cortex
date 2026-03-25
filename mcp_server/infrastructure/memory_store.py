"""Memory store compatibility layer.

Routes all storage through PgMemoryStore (PostgreSQL + pgvector).
Accepts the legacy (db_path, embedding_dim) constructor signature
so all 42+ importing files continue to work without modification.

The old SQLite backend is fully replaced. PostgreSQL is mandatory.
"""

from __future__ import annotations

import warnings
from typing import Any

from mcp_server.infrastructure.pg_store import PgMemoryStore


class MemoryStore(PgMemoryStore):
    """Backward-compatible wrapper over PgMemoryStore.

    Accepts the old ``(db_path, embedding_dim)`` constructor but
    ignores both — PostgreSQL config comes from DATABASE_URL env var
    (or the ``MemorySettings.DATABASE_URL`` default).
    """

    def __init__(
        self,
        db_path: str = "",
        embedding_dim: int = 384,
        *,
        database_url: str | None = None,
    ) -> None:
        if db_path:
            warnings.warn(
                "MemoryStore(db_path=...) is deprecated. "
                "PostgreSQL is now the sole backend. "
                "Set DATABASE_URL env var instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        super().__init__(database_url=database_url)

    # Expose _row_to_dict for any code that still calls it
    def _row_to_dict(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        """Legacy alias for _normalize_memory_row."""
        if row is None:
            return None
        return self._normalize_memory_row(row)
