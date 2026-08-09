"""capture_origin passthrough in mcp_server.core.memory_ingest (issue #368 fix).

Contract under test: ingest_memory forwards the caller-supplied
`capture_origin` field to `store.insert_memory` exactly like every other
metadata field (source, tags, heat, ...) instead of dropping it — the gap
that made the trust-factor gated arm (docs/provenance/
trust-factor-calibration.md) unable to discriminate W, because every
LME/LoCoMo/BEAM row silently fell through to insert_memory's "unknown"
default regardless of what the harness intended.
"""

from __future__ import annotations

import pytest

from mcp_server.core.memory_ingest import ingest_memory
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture
def store():
    s = SqliteMemoryStore()
    yield s
    s.close()


class _NullEmbeddings:
    """No-op embeddings engine — this suite asserts metadata passthrough,
    not ranking, so a real embedding model is unnecessary weight."""

    def encode(self, _text: str):
        return None


def _fetch_capture_origin(store: SqliteMemoryStore, memory_id: int) -> str:
    row = store._conn.execute(
        "SELECT capture_origin FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    return row["capture_origin"]


class TestCaptureOriginPassthrough:
    def test_explicit_origin_is_forwarded(self, store):
        ids = ingest_memory(
            {"content": "hello world", "capture_origin": "network"},
            store,
            _NullEmbeddings(),
            domain="test",
            decompose=False,
        )
        assert len(ids) == 1
        assert _fetch_capture_origin(store, ids[0]) == "network"

    def test_omitted_origin_defaults_to_unknown(self, store):
        """Unchanged production behaviour: a caller that says nothing about
        origin still gets 'unknown' — the fix only stops DROPPING a value
        the caller DID provide."""
        ids = ingest_memory(
            {"content": "hello world, no origin set"},
            store,
            _NullEmbeddings(),
            domain="test",
            decompose=False,
        )
        assert len(ids) == 1
        assert _fetch_capture_origin(store, ids[0]) == "unknown"

    def test_all_chunks_of_a_decomposed_memory_share_the_parent_origin(self, store):
        """decompose=True splits one memory into several insert_memory rows
        (memory_decomposer.py); every chunk came through the same channel as
        its parent, so every chunk must carry the same capture_origin."""
        long_content = "\n".join(
            f"## Section {i}\ncontent for section {i} " * 10 for i in range(5)
        )
        ids = ingest_memory(
            {"content": long_content, "capture_origin": "deliberate"},
            store,
            _NullEmbeddings(),
            domain="test",
            decompose=True,
        )
        assert len(ids) >= 1
        origins = {_fetch_capture_origin(store, mid) for mid in ids}
        assert origins == {"deliberate"}
