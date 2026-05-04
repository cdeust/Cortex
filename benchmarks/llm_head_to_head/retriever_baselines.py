"""Condition B — standard top-20 cosine RAG (Lewis et al. 2020).

Protocol §2.B and §11.1 anti-cheating clauses:
- Embed the question with ``sentence-transformers/all-MiniLM-L6-v2``
  (the SAME model Cortex uses, so the comparison isolates the retrieval
  *stack*, not the embedding choice).
- Direct cosine top-k against the same ``embedding`` column via the HNSW
  index. NO ``recall_memories()`` PL/pgSQL fusion. NO heat. NO recency.
  NO trigram. NO FlashRank rerank. NO co-activation. NO strategic
  ordering. NO production enrichments. This is canonical Lewis-2020.

The implementation deliberately uses a SEPARATE code path from
``mcp_server/handlers/recall.py``. The unit test
``tests_py/benchmarks/test_beam_standard_rag.py`` asserts this module
does NOT import from ``mcp_server.handlers.recall``.

precondition: items are loaded into a per-conversation ephemeral PG store
  via ``benchmarks.lib.bench_db.BenchmarkDB``; the ``embedding`` column
  is HNSW-indexed (cosine).
postcondition: returns the top-k memory dicts ordered by cosine similarity
  (highest first) — no other ranking factor.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# We deliberately import ONLY:
#   1. the embedding engine (same model Cortex uses; isolates retrieval-
#      stack effects from embedding-choice effects).
#   2. the BenchmarkDB ephemeral store (data plumbing).
# We deliberately do NOT import:
#   - mcp_server.handlers.recall  (protocol §11.1 anti-cheating)
#   - mcp_server.core.pg_recall   (PL/pgSQL fusion is the Cortex stack)
#   - mcp_server.core.reranker    (FlashRank is the Cortex stack)
#
# The test ``test_beam_standard_rag.py`` enforces this invariant by
# parsing the source of this module.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server.infrastructure.embedding_engine import get_embedding_engine  # noqa: E402

# Pre-registered top-k value (protocol §2.B, no sweep).
STANDARD_RAG_TOP_K = 20


@dataclass(frozen=True)
class RagPassage:
    memory_id: int
    content: str
    cosine: float


def standard_rag(
    question: str,
    db: Any,  # BenchmarkDB-like; duck-typed to avoid heavy import at module load
    top_k: int = STANDARD_RAG_TOP_K,
) -> list[RagPassage]:
    """Vanilla top-k cosine retrieval over the BEAM-loaded memories.

    pre:
      - ``db`` exposes a ``conn`` attribute with a psycopg connection
        bound to a database where the BEAM memories have been loaded
        with their 384-dim ``embedding`` column populated.
      - ``question`` is a non-empty string.
    post:
      - returns a list of length ≤ ``top_k`` ordered by cosine similarity
        (descending); each ``RagPassage`` carries the raw memory_id, its
        content, and the cosine score.
      - NO heat / FTS / trigram / WRRF / rerank applied.
    invariant:
      - the SQL query references ONLY the ``embedding`` column with the
        ``vector_cosine_ops`` operator class (``<=>``); no joins to heat,
        no full-text predicates, no time decay. This is the contract
        that makes B distinguishable from C.

    source: Lewis, P. et al. (2020), *Retrieval-Augmented Generation for
      Knowledge-Intensive NLP Tasks*, NeurIPS. Reference architecture.
    """
    if not question or not question.strip():
        return []

    # Encode question. The production embedding engine returns a float32
    # byte blob (see ``EmbeddingEngine.encode``); we convert to a numpy
    # array so the pgvector psycopg adapter (registered on the connection)
    # can bind it as a ``vector`` parameter — same convention as
    # ``mcp_server.infrastructure.pg_store.search_vectors``.
    emb = get_embedding_engine()
    qbytes = emb.encode(question)
    if qbytes is None:
        return []
    qvec = np.frombuffer(qbytes, dtype=np.float32)

    # pgvector cosine distance: a <=> b ∈ [0, 2]; cosine_sim = 1 - dist.
    # We pull memory_id, content, and the distance ordered ASC (closest
    # first). No filters by domain, heat, or anything else — vanilla
    # Lewis-2020 RAG. The ``register_vector`` adapter on ``db.conn``
    # (PgMemoryStore.__init__) handles the numpy → ``vector`` binding,
    # so we do NOT need an explicit ``::vector`` cast in the SQL.
    sql = (
        "SELECT id, content, embedding <=> %s AS cdist "
        "FROM memories "
        "WHERE embedding IS NOT NULL "
        "ORDER BY embedding <=> %s ASC "
        "LIMIT %s"
    )
    conn = _resolve_conn(db)
    with conn.cursor() as cur:
        cur.execute(sql, (qvec, qvec, top_k))
        rows = cur.fetchall()

    return [
        RagPassage(
            memory_id=_row_field(row, 0, "id"),
            content=_row_field(row, 1, "content") or "",
            cosine=1.0 - float(_row_field(row, 2, "cdist")),
        )
        for row in rows
    ]


def _resolve_conn(db: Any) -> Any:
    """Pull the psycopg connection out of a BenchmarkDB-like object.

    pre: ``db`` exposes either a ``.conn`` attribute or a ``._store._conn``
      attribute (BenchmarkDB wraps a ``PgMemoryStore`` with the conn under
      ``_store._conn``).
    post: returns a psycopg connection object with ``register_vector`` already
      registered (production __init__ does this on construction).
    """
    if hasattr(db, "conn"):
        return db.conn
    store = getattr(db, "_store", None)
    if store is not None and hasattr(store, "_conn"):
        return store._conn
    raise AttributeError(
        "standard_rag: db argument must expose a psycopg connection via "
        "`.conn` or `._store._conn` (BenchmarkDB shape)."
    )


def _row_field(row: Any, index: int, key: str) -> Any:
    """Read a row field tolerant of tuple-row and dict-row factories.

    pre: ``row`` is either an indexable (tuple/list) or a mapping (dict_row).
    post: returns the value at that position/key; raises KeyError/IndexError
      consistent with the underlying type.
    """
    if isinstance(row, dict):
        return row[key]
    return row[index]


def passages_to_context(passages: list[RagPassage], separator: str = "\n\n") -> str:
    """Concatenate top-k passages into the answer prompt's CONTEXT field.

    pre: passages are already ranked best-first.
    post: returns a string with one passage per separator-delimited block;
      empty string when passages is empty.
    """
    return separator.join(p.content for p in passages if p.content)
