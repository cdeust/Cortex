"""Memory store — PostgreSQL + pgvector.

Re-exports PgMemoryStore as MemoryStore with backward-compatible
constructor accepting (db_path, embedding_dim) — both ignored.
PostgreSQL config comes from DATABASE_URL env var.
"""

from __future__ import annotations

from mcp_server.infrastructure.pg_store import PgMemoryStore


class MemoryStore(PgMemoryStore):
    """PgMemoryStore with backward-compatible constructor.

    Accepts ``(db_path, embedding_dim)`` for callers that haven't
    been updated yet. Both are ignored — PostgreSQL is mandatory.
    """

    def __init__(
        self,
        db_path: str = "",
        embedding_dim: int = 384,
        *,
        database_url: str | None = None,
    ) -> None:
        super().__init__(database_url=database_url)
