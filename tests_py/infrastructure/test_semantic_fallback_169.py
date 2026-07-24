"""Semantic fallback + code-aware FTS integration tests (issue #169).

Contract assertions (each must fail on regression):
  - Engine engages fallback mode LOUDLY when no model is loadable, with zero
    network, producing dim-correct deterministic vectors.
  - Fresh SQLite store answers a semantic recall correctly in fallback mode
    with no network (remember + recall round-trip).
  - camelCase memory content is matched by a plain-word FTS query (and vice
    versa) via index-time augmentation + query-time expansion.
  - Mixed store: a neural-tagged vector is NOT returned by the vector signal
    when the process is in fallback mode (no silent cross-ranking).
  - The external-content → self-content FTS migration reindexes cleanly.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

import mcp_server.infrastructure.embedding_engine as ee
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture()
def fallback_engine(monkeypatch):
    """Install a process-wide engine forced into fallback mode; restore after."""
    monkeypatch.setenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "1")
    saved = ee._singleton
    eng = ee.EmbeddingEngine(model_name="no-such-model-xyz-169", dim=384)
    ee._singleton = eng
    assert eng.mode == "fallback"
    yield eng
    ee._singleton = saved


@pytest.fixture()
def store():
    s = SqliteMemoryStore(db_path=":memory:", embedding_dim=384)
    yield s
    s.close()


def test_engine_engages_fallback_loudly(monkeypatch, caplog):
    monkeypatch.setenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "1")
    eng = ee.EmbeddingEngine(model_name="no-such-model-xyz-169", dim=384)
    with caplog.at_level(logging.WARNING):
        blob = eng.encode("normalizePaymentAmount rounds the charge")
    assert eng.mode == "fallback"
    vec = np.frombuffer(blob, dtype=np.float32)
    assert vec.shape == (384,)
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-5
    # LOUD: exactly one fallback warning naming the issue
    assert any("fallback ENGAGED" in r.message for r in caplog.records)
    # deterministic across calls
    assert blob == eng.encode("normalizePaymentAmount rounds the charge")


def test_zero_network_semantic_roundtrip(fallback_engine, store):
    eng = fallback_engine
    memories = [
        "The checkoutService wraps read-charge-decrement in one DB transaction",
        "normalizePaymentAmount rounds the charge to cents before billing",
        "We went hiking in the alps and the weather was sunny all week",
    ]
    for text in memories:
        store.insert_memory(
            {"content": text, "embedding": eng.encode(text), "heat": 0.8}
        )
    query = "how does payment amount normalization work"
    results = store.recall_memories(query, eng.encode(query), max_results=3)
    assert results
    assert "normalizePaymentAmount" in results[0]["content"]


def test_camelcase_fts_match_both_directions(fallback_engine, store):
    store.insert_memory(
        {"content": "normalizePaymentAmount rounds the charge", "embedding": None}
    )
    # plain-word query matches camelCase content (index-time augmentation)
    assert store.search_fts("payment")
    # camelCase query matches (query-time expansion) even with no vector
    assert store.search_fts("normalizePaymentAmount")


def test_embedding_model_stamped_fallback(fallback_engine, store):
    eng = fallback_engine
    mid = store.insert_memory(
        {"content": "a decision", "embedding": eng.encode("a decision")}
    )
    row = store._conn.execute(
        "SELECT embedding_model FROM memories WHERE id = ?", (mid,)
    ).fetchone()
    assert row["embedding_model"] == "fallback"


def test_mixed_store_no_cross_rank(fallback_engine, store):
    """A neural vector must not be vector-ranked against a fallback query."""
    eng = fallback_engine
    query = "payment normalization"
    q_vec = eng.encode(query)
    # Fallback memory (normal write path → tagged 'fallback').
    fb_id = store.insert_memory(
        {
            "content": "payment normalization to cents",
            "embedding": eng.encode("x"),
            "heat": 0.5,
        }
    )
    # Neural memory whose stored vector is IDENTICAL to the query vector — it
    # would win the vector KNN outright if cross-space filtering were absent.
    neural_id = store.insert_memory(
        {
            "content": "unrelated neural-tagged row",
            "embedding": q_vec,
            "embedding_model": "neural",
            "heat": 0.5,
        }
    )
    # Vector-only recall (other signals zeroed) in fallback mode.
    results = store.recall_memories(
        query,
        q_vec,
        max_results=5,
        weights={"vector": 1.0, "fts": 0.0, "heat": 0.0, "recency": 0.0},
    )
    ids = {r["memory_id"] for r in results}
    assert neural_id not in ids  # neural vector excluded from fallback query
    assert fb_id in ids  # same-space fallback vector retained


def test_select_fallback_embeddings_worklist(fallback_engine, store):
    eng = fallback_engine
    store.insert_memory(
        {"content": "fb one", "embedding": eng.encode("fb one"), "heat": 0.9}
    )
    store.insert_memory(
        {
            "content": "neural one",
            "embedding": eng.encode("n"),
            "embedding_model": "neural",
        }
    )
    work = store.select_fallback_embeddings(limit=10)
    contents = {w["content"] for w in work}
    assert "fb one" in contents
    assert "neural one" not in contents


def test_fts_migration_rebuilds_external_content(tmp_path):
    """A legacy external-content memories_fts is converted + reindexed."""
    db = str(tmp_path / "legacy.db")
    # Build a store, then rewrite memories_fts as an OLD external-content table
    # with a row inserted the pre-#169 way (raw content, no sub-tokens).
    s = SqliteMemoryStore(db_path=db, embedding_dim=384)
    mid = s.insert_memory({"content": "legacyCamelToken here", "embedding": None})
    s._conn.execute("DROP TABLE memories_fts")
    s._conn.execute(
        "CREATE VIRTUAL TABLE memories_fts USING fts5("
        "content, content='memories', content_rowid='id')"
    )
    s._conn.execute(
        "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
        (mid, "legacyCamelToken here"),
    )
    s._conn.commit()
    s.close()
    # Reopen → migration should detect external-content and rebuild+reindex.
    s2 = SqliteMemoryStore(db_path=db, embedding_dim=384)
    sql = s2._conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='memories_fts'"
    ).fetchone()["sql"]
    assert "content=" not in sql
    # sub-token now indexed → plain-word query matches the camelCase memory
    assert s2.search_fts("camel")
    s2.close()
