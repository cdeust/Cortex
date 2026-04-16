"""E2 — SHA-keyed embedding cache (ADR-0045 R5).

Verifies two properties of the cache key discipline:

  (a) Hit/miss correctness — identical input texts resolve to the same
      cache entry and return the same bytes; different texts do not
      collide.
  (b) Bounded key size — the cache key length is constant (16 hex chars)
      regardless of input text length. A 100 KB text must not produce a
      100 KB key.

Source: ADR-0045 §R5 — "No text-keyed dicts or caches on user content.
Any memoization layer over user-provided strings must use
``hashlib.sha256(text.encode()).hexdigest()[:16]`` as the cache key."
"""

from __future__ import annotations

import hashlib

from mcp_server.infrastructure.embedding_engine import EmbeddingEngine


# ── (a) Hit / miss correctness ─────────────────────────────────────────


class TestCacheHitMiss:
    def test_same_text_returns_same_bytes(self):
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        first = engine.encode("hello world")
        second = engine.encode("hello world")
        assert first == second  # same bytes from cache

    def test_same_text_is_single_cache_entry(self):
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        engine.encode("repeat me")
        engine.encode("repeat me")
        engine.encode("repeat me")
        assert len(engine._cache) == 1

    def test_different_text_different_cache_entries(self):
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        engine.encode("alpha")
        engine.encode("beta")
        assert len(engine._cache) == 2

    def test_miss_then_hit(self):
        """First call populates cache; second call returns cached value."""
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        # Miss — nothing cached yet.
        assert len(engine._cache) == 0
        engine.encode("fresh text")
        assert len(engine._cache) == 1
        # Hit — no new entry added.
        engine.encode("fresh text")
        assert len(engine._cache) == 1


# ── (b) Bounded key size — the reason R5 exists ───────────────────────


class TestCacheKeyBounded:
    def test_cache_key_is_16_chars(self):
        """The cache key for any input is sha256[:16] — 16 hex chars."""
        key = EmbeddingEngine._cache_key("anything")
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)

    def test_cache_key_independent_of_text_length(self):
        """100 KB input must produce a 16-char key, not a 100 KB key."""
        short = EmbeddingEngine._cache_key("x")
        huge = EmbeddingEngine._cache_key("x" * 100_000)
        assert len(short) == len(huge) == 16

    def test_cache_key_deterministic(self):
        a = EmbeddingEngine._cache_key("stable")
        b = EmbeddingEngine._cache_key("stable")
        assert a == b

    def test_cache_key_matches_adr_formula(self):
        """Formula must match ADR-0045 R5 verbatim."""
        text = "audit-proof example"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        assert EmbeddingEngine._cache_key(text) == expected

    def test_cache_entries_stay_16_char_keys_after_100kb_inserts(self):
        """Insert several 100 KB texts; every cache key is 16 chars."""
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        for i in range(5):
            big = (f"{i}" * 25_000)  # 25 K * 1 byte each = 25 KB; across
            # the five calls the cache's accumulated raw-text bytes, if
            # stored as keys, would be 125 KB. With hashed keys it stays
            # at 5 * 16 = 80 bytes.
            engine.encode(big)
        # All cached keys must be exactly 16 hex chars. A regression to
        # raw-text keys would produce 25_000-char keys here.
        for key in engine._cache.keys():
            assert len(key) == 16
            assert all(c in "0123456789abcdef" for c in key)
        # Total key byte budget: 5 entries * 16 chars = 80 bytes
        # (ignoring Python str overhead). Raw-text keys would be
        # 125 KB — three orders of magnitude larger.
        total_key_bytes = sum(len(k) for k in engine._cache.keys())
        assert total_key_bytes <= 5 * 16  # hashed keys only


class TestCollisionSurface:
    """Sanity check: the 16-char SHA256 prefix is deterministic and the
    two paper-cited equal texts collide only when they are literally
    identical (up to encoding). This is not a cryptographic test — it
    just guards against an accidental truncation bug."""

    def test_distinct_texts_distinct_keys(self):
        texts = [
            "the quick brown fox",
            "the quick brown fox ",  # trailing space
            "The quick brown fox",  # capital T
            "",  # empty — explicitly allowed by _cache_key (caller guards)
            "🦊 unicode",
            "a" * 10_000,
            "a" * 10_001,
        ]
        keys = {EmbeddingEngine._cache_key(t) for t in texts}
        # All 7 inputs differ → all 7 keys differ.
        assert len(keys) == len(texts)
