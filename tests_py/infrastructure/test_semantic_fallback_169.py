"""Semantic fallback (#169 Phase B) — provider selection, stamp, mixed store.

Covers the Phase B contract items:
  1. Algorithmic fallback is a SECOND EmbeddingProvider selected per ModelState;
     no state maps to nothing (factory.use_fallback is total).
  2. embedding_model is stamped UNCONDITIONALLY on remember — 'fallback' even
     when sqlite-vec is absent (no vec row), never ''.
  3. Fallback engagement is LOUD (one WARNING) + telemetry embedding_mode.
  6. Genuine (not monkeypatched) sentence-transformers absence via subprocess.
  8. Mixed store: neural and fallback vectors never cross-rank.
Plus the external-content → self-content FTS migration.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import textwrap

import numpy as np
import pytest

import mcp_server.infrastructure.embedding_engine as ee
import mcp_server.infrastructure.embedding_factory as ef
from mcp_server.infrastructure.embedding_fallback_provider import (
    AlgorithmicEmbeddingProvider,
)
from mcp_server.infrastructure.embedding_model_lifecycle import ModelState
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


def _sqlite_vec_available() -> bool:
    s = SqliteMemoryStore(db_path=":memory:", embedding_dim=384)
    try:
        return bool(s._has_vec)
    finally:
        s.close()


_HAS_VEC = _sqlite_vec_available()
_needs_vec = pytest.mark.skipif(
    not _HAS_VEC,
    reason="sqlite-vec not installed ([sqlite] extra); vector path unavailable",
)


@pytest.fixture()
def fallback_engine(monkeypatch):
    """Install a process-wide engine forced into fallback mode; restore after."""
    monkeypatch.setenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "1")
    saved = ef._singleton
    eng = ee.EmbeddingEngine(model_name="no-such-model-169b", dim=384)
    ef._singleton = eng
    assert eng.mode == "fallback"
    yield eng
    ef._singleton = saved


@pytest.fixture()
def store():
    s = SqliteMemoryStore(db_path=":memory:", embedding_dim=384)
    yield s
    s.close()


# ── Item 1: second provider, selected per ModelState, total mapping ──────────


def test_fallback_provider_is_embedding_provider():
    from mcp_server.infrastructure.embedding_provider import EmbeddingProvider

    p = AlgorithmicEmbeddingProvider(dim=384)
    assert isinstance(p, EmbeddingProvider)
    blob = p.encode("normalizePaymentAmount rounds the charge")
    assert blob is not None and len(blob) == 384 * 4
    assert p.encode("") is None
    assert not p.available


def test_use_fallback_mapping_is_total():
    # Every non-LOADED state routes to fallback; LOADED → neural. No gaps.
    for state in ModelState:
        assert ef.use_fallback(state) is (state is not ModelState.LOADED)


def test_engine_selects_fallback_for_absent_states(fallback_engine):
    eng = fallback_engine
    # A bogus model + zero-download resolves to a non-LOADED state.
    assert eng.model_state in {
        ModelState.MODEL_FILES_ABSENT,
        ModelState.PACKAGE_ABSENT,
        ModelState.LOAD_RAISED,
    }
    assert eng.mode == "fallback"
    a = eng.encode("payment normalization to cents")
    b = eng.encode("payment normalization to cents")
    assert a is not None and a == b  # deterministic algorithmic vector


# ── Item 3: loud engagement + deterministic dim ──────────────────────────────


def test_engine_engages_fallback_loudly(monkeypatch, caplog):
    monkeypatch.setenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "1")
    eng = ee.EmbeddingEngine(model_name="no-such-model-169b", dim=384)
    with caplog.at_level(logging.WARNING):
        blob = eng.encode("normalizePaymentAmount rounds the charge")
    assert eng.mode == "fallback"
    vec = np.frombuffer(blob, dtype=np.float32)
    assert vec.shape == (384,)
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-5
    assert any("fallback ENGAGED" in r.message for r in caplog.records)


# ── Item 2: unconditional stamp (works without sqlite-vec) ───────────────────


def test_embedding_model_stamped_fallback(fallback_engine, store):
    eng = fallback_engine
    mid = store.insert_memory(
        {"content": "a decision", "embedding": eng.encode("a decision")}
    )
    row = store._conn.execute(
        "SELECT embedding_model FROM memories WHERE id = ?", (mid,)
    ).fetchone()
    # Never '' — stamped even if the vec store is absent (issue #169 root cause).
    assert row["embedding_model"] == "fallback"


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
    contents = {w["content"] for w in store.select_fallback_embeddings(limit=10)}
    assert "fb one" in contents
    assert "neural one" not in contents


# ── camelCase FTS (index-time augmentation) ──────────────────────────────────


def test_camelcase_fts_match(fallback_engine, store):
    store.insert_memory(
        {"content": "normalizePaymentAmount rounds the charge", "embedding": None}
    )
    assert store.search_fts("payment")  # sub-token indexed by augment_content
    assert store.search_fts("normalizePaymentAmount")


# ── Item 4: recall_helpers path recalls camelCase via lowercase query ────────


@_needs_vec
def test_recall_helpers_camelcase_lowercase_query(fallback_engine, store):
    from mcp_server.handlers.recall_helpers import compute_vector_fts

    eng = fallback_engine
    mid = store.insert_memory(
        {
            "content": "normalizePaymentAmount rounds the charge to cents",
            "embedding": eng.encode("normalizePaymentAmount rounds the charge"),
            "heat": 0.8,
        }
    )
    # Lowercase natural-language query must recall the camelCase symbol memory
    # through the recall_helpers FTS path.
    _vec, fts, _q = compute_vector_fts("payment", store, eng, pool=20, min_heat=0.0)
    assert mid in {m for m, _ in fts}


# ── Item 8: mixed store — no cross-rank ──────────────────────────────────────


@_needs_vec
def test_mixed_store_no_cross_rank(fallback_engine, store):
    eng = fallback_engine
    query = "payment normalization"
    q_vec = eng.encode(query)
    fb_id = store.insert_memory(
        {
            "content": "payment normalization to cents",
            "embedding": eng.encode("x"),
            "heat": 0.5,
        }
    )
    # A neural-tagged vector identical to the query — would win the KNN if the
    # spaces were allowed to cross-rank.
    neural_id = store.insert_memory(
        {
            "content": "unrelated neural-tagged row",
            "embedding": q_vec,
            "embedding_model": "neural",
            "heat": 0.5,
        }
    )
    results = store.recall_memories(
        query,
        q_vec,
        max_results=5,
        weights={"vector": 1.0, "fts": 0.0, "heat": 0.0, "recency": 0.0},
    )
    ids = {r["memory_id"] for r in results}
    assert neural_id not in ids
    assert fb_id in ids


# ── Item 5: scheduled upgrade via consolidate cycle ──────────────────────────


@_needs_vec
def test_embedding_upgrade_cycle_restamps_neural(monkeypatch, store):
    """Fallback-stamped memories + neural model available → restamped neural."""
    from mcp_server.handlers.consolidation.embedding_upgrade import (
        run_embedding_upgrade_cycle,
    )

    # 1) Write two memories under the fallback provider (model absent).
    monkeypatch.setenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "1")
    saved = ef._singleton
    fb = ee.EmbeddingEngine(model_name="no-such-model-169b", dim=384)
    ef._singleton = fb
    try:
        for text in [
            "decision about the checkout transaction",
            "payment rounding rule",
        ]:
            store.insert_memory({"content": text, "embedding": fb.encode(text)})
        assert len(store.select_fallback_embeddings(limit=10)) == 2

        # 2) Model now available: a real neural engine as the process encoder.
        monkeypatch.delenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", raising=False)
        neural = ee.EmbeddingEngine(dim=384)
        if neural.mode != "neural":
            pytest.skip("neural model not cached in this environment")
        ef._singleton = neural

        # 3) Consolidate's upgrade cycle re-embeds + restamps.
        result = run_embedding_upgrade_cycle(store, neural)
        assert result["upgraded"] == 2
        assert store.select_fallback_embeddings(limit=10) == []
        stamps = {
            r["embedding_model"]
            for r in store._conn.execute(
                "SELECT embedding_model FROM memories"
            ).fetchall()
        }
        assert stamps == {"neural"}
    finally:
        ef._singleton = saved


def test_consolidate_reports_embedding_upgrade(fallback_engine, store):
    """The upgrade cycle reports a count even when nothing needs upgrading."""
    from mcp_server.handlers.consolidation.embedding_upgrade import (
        run_embedding_upgrade_cycle,
    )

    # Encoder is fallback → cycle is a no-op but still reports structure.
    out = run_embedding_upgrade_cycle(store, fallback_engine)
    assert out["upgraded"] == 0
    assert "reason" in out


# ── FTS migration: external-content → self-content ───────────────────────────


def test_fts_migration_rebuilds_external_content(tmp_path):
    db = str(tmp_path / "legacy.db")
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
    s2 = SqliteMemoryStore(db_path=db, embedding_dim=384)
    sql = s2._conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='memories_fts'"
    ).fetchone()["sql"]
    assert "content=" not in sql
    assert s2.search_fts("camel")  # sub-token now indexed
    s2.close()


# ── Item 6: GENUINE sentence-transformers absence (subprocess) ───────────────

_CHILD = textwrap.dedent(
    """
    import json, sys

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name == "sentence_transformers" or name.startswith(
                "sentence_transformers."
            ):
                raise ModuleNotFoundError("sentence_transformers hidden for test")
            return None

    sys.meta_path.insert(0, _Block())

    import mcp_server.infrastructure.embedding_factory as ef
    import mcp_server.infrastructure.embedding_engine as ee
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

    eng = ee.EmbeddingEngine(dim=384)  # default (real) model name; ST import fails
    ef._singleton = eng
    blob = eng.encode("normalizePaymentAmount rounds the charge to cents")

    store = SqliteMemoryStore(db_path=":memory:", embedding_dim=384)
    for text in [
        "The checkoutService wraps read-charge-decrement in one DB transaction",
        "normalizePaymentAmount rounds the charge to cents before billing",
        "we hiked in the alps under sunny weather all week",
    ]:
        store.insert_memory(
            {"content": text, "embedding": eng.encode(text), "heat": 0.8}
        )

    stamp = store._conn.execute(
        "SELECT embedding_model FROM memories LIMIT 1"
    ).fetchone()["embedding_model"]
    q = "how does payment amount normalization work"
    res = store.recall_memories(q, eng.encode(q), max_results=3)
    print(
        "RESULT_JSON:"
        + json.dumps(
            {
                "mode": eng.mode,
                "state": eng.model_state.name,
                "has_blob": bool(blob),
                "has_vec": bool(store._has_vec),
                "stamp": stamp,
                "top": res[0]["content"] if res else "",
            }
        )
    )
    """
)


def test_real_sentence_transformers_absence_subprocess(monkeypatch):
    # Empty HF_HOME + genuine ImportError: zero network, pure fallback.
    monkeypatch.setenv("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "1")
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"child failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT_JSON:"))
    out = json.loads(line[len("RESULT_JSON:") :])
    assert out["mode"] == "fallback"
    assert out["state"] == "PACKAGE_ABSENT"
    assert out["has_blob"] is True
    assert out["stamp"] == "fallback"
    if out["has_vec"]:
        assert "normalizePaymentAmount" in out["top"]
