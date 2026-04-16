"""F4 — redundant embedding-encode elimination on 0 → 2 compression.

Previously a 0 → 2 compression path called ``embeddings.encode()`` three
times:

    1. once for the gist (level 1 write + archive)
    2. once for the gist again (archive row inside the tag step — REDUNDANT)
    3. once for the tag (level 2 write)

The fix threads the already-computed gist + gist embedding from the
``_compress_full_to_gist`` call into ``_compress_to_tag_from_gist``, so
call #2 is gone. Regression guard: a spy on ``encode`` asserts exactly
2 calls on a 0 → 2 transition (down from 3) and 1 call on a 0 → 1
transition.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from mcp_server.handlers.consolidation import compression as compression_handler


class _SpyEmbeddings:
    """Records how many times ``encode`` is called and with what input."""

    def __init__(self):
        self.calls: list[str] = []

    def encode(self, text: str) -> list[float]:
        self.calls.append(text)
        # Return a deterministic fake vector; value doesn't matter here.
        return [float(len(text)), float(hash(text) % 1000) / 1000.0]


class _FakeStore:
    """Minimal fake store: records writes, ignores reads."""

    def __init__(self):
        self.archives: list[dict] = []
        self.updates: list[tuple] = []

    def insert_archive(self, row: dict) -> int:
        self.archives.append(row)
        return len(self.archives)

    def update_memory_compression(
        self,
        mem_id: int,
        content: str,
        embedding: list[float],
        level: int,
        *,
        original_content: str | None = None,
    ) -> None:
        self.updates.append((mem_id, content, embedding, level, original_content))


def _make_settings(gist_hours: float, tag_hours: float) -> MagicMock:
    s = MagicMock()
    s.COMPRESSION_GIST_AGE_HOURS = gist_hours
    s.COMPRESSION_TAG_AGE_HOURS = tag_hours
    return s


def _mem(age_hours: float, *, mid: int = 1) -> dict:
    created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {
        "id": mid,
        "content": (
            "First sentence. Second sentence with details. Third sentence. "
            "Fourth sentence for bulk. Fifth sentence closes the memory."
        ),
        "compression_level": 0,
        "created_at": created.isoformat(),
        "importance": 0.3,
        "store_type": "episodic",
        "embedding": [0.0, 0.0],
        "surprise_score": 0.0,
        "confidence": 0.5,
        "access_count": 0,
    }


class TestEncodeCount:
    """Regression guard on the encode-call count per transition path."""

    def test_0_to_2_transition_calls_encode_exactly_twice(self):
        """0 → 2: one encode for the gist, one for the tag. No redundant re-encode."""
        settings = _make_settings(gist_hours=168.0, tag_hours=720.0)
        embeddings = _SpyEmbeddings()
        store = _FakeStore()
        # 2000 hours old → target level 2.
        mem = _mem(age_hours=2000.0)
        stats = {
            "compressed_to_gist": 0,
            "compressed_to_tag": 0,
        }

        compression_handler._compress_memory(
            store, settings, embeddings, mem, stats
        )

        # Exactly 2 encode calls — down from 3 before the fix.
        assert len(embeddings.calls) == 2, (
            f"expected 2 encode() calls on 0 → 2, got {len(embeddings.calls)}: "
            f"{embeddings.calls}"
        )
        # Both the gist-level-1 archive and the tag-level-2 update happened.
        assert stats["compressed_to_gist"] == 1
        assert stats["compressed_to_tag"] == 1
        # Two archive rows: one at the gist step (reason=compression_gist),
        # one at the tag step (reason=compression_tag, reusing gist_emb).
        assert len(store.archives) == 2
        assert store.archives[0]["archive_reason"] == "compression_gist"
        assert store.archives[1]["archive_reason"] == "compression_tag"
        # Two memory updates: level 1 first, then level 2.
        assert [u[3] for u in store.updates] == [1, 2]

    def test_0_to_1_transition_calls_encode_exactly_once(self):
        """0 → 1: one encode for the gist. No tag step."""
        settings = _make_settings(gist_hours=168.0, tag_hours=720.0)
        embeddings = _SpyEmbeddings()
        store = _FakeStore()
        # 200 hours old → target level 1 (past gist, not past tag).
        mem = _mem(age_hours=200.0)
        stats = {
            "compressed_to_gist": 0,
            "compressed_to_tag": 0,
        }

        compression_handler._compress_memory(
            store, settings, embeddings, mem, stats
        )

        assert len(embeddings.calls) == 1, (
            f"expected 1 encode() call on 0 → 1, got {len(embeddings.calls)}"
        )
        assert stats["compressed_to_gist"] == 1
        assert stats["compressed_to_tag"] == 0

    def test_1_to_2_transition_calls_encode_exactly_once(self):
        """1 → 2: one encode for the tag (legacy path, unchanged)."""
        settings = _make_settings(gist_hours=168.0, tag_hours=720.0)
        embeddings = _SpyEmbeddings()
        store = _FakeStore()
        # 2000 hours old → target level 2.
        mem = _mem(age_hours=2000.0)
        mem["compression_level"] = 1
        mem["content"] = "Already a gist."
        stats = {
            "compressed_to_gist": 0,
            "compressed_to_tag": 0,
        }

        compression_handler._compress_memory(
            store, settings, embeddings, mem, stats
        )

        assert len(embeddings.calls) == 1
        assert stats["compressed_to_gist"] == 0
        assert stats["compressed_to_tag"] == 1

    def test_legacy_call_without_gist_args_still_works(self):
        """Direct call to _compress_to_tag_from_gist w/o the fast-path args.

        Ensures the legacy code path (unused by the new _compress_memory but
        kept for API stability) still encodes twice — the gist for the archive,
        and the tag for the update.
        """
        embeddings = _SpyEmbeddings()
        store = _FakeStore()
        mem = _mem(age_hours=2000.0)
        stats = {"compressed_to_tag": 0}

        compression_handler._compress_to_tag_from_gist(
            store, embeddings, mem, stats
        )

        assert len(embeddings.calls) == 2
        assert stats["compressed_to_tag"] == 1
