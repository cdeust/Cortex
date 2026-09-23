"""Unit tests for handlers.consolidation.wiki_backlog_pass's G-2 grooming
addition (2026-07-11): the lesson_promotion backlog count report.

Monkeypatch-based — the coverage/cluster/drift audits this module also
runs touch the real filesystem WIKI_ROOT and are out of scope here;
this file isolates the one new mechanical field.
"""

from __future__ import annotations

import pytest

from mcp_server.handlers.consolidation import wiki_backlog_pass


class _FakeConn:
    pass


class _FakeCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc):
        return False


class _FakeBatchPool:
    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        return _FakeCtx(self._conn)


class _StoreWithPool:
    def __init__(self):
        self.batch_pool = _FakeBatchPool(_FakeConn())


class _StoreWithoutPool:
    """Mimics the SQLite fallback store — no ``batch_pool`` attribute."""


class TestLessonPromotionBacklog:
    def test_returns_count_on_success(self, monkeypatch) -> None:
        # Patch the consumer's binding (top-level import, #197 family 4).
        monkeypatch.setattr(
            wiki_backlog_pass, "count_lesson_promotion_candidates", lambda conn: 133
        )

        result = wiki_backlog_pass._lesson_promotion_backlog(_StoreWithPool())

        assert result == 133

    def test_raises_when_store_lacks_batch_pool(self) -> None:
        """#636: calling this without ``batch_pool`` is a wiring bug (the
        sole caller, ``run_wiki_maintenance``, gates on it once) and
        raises rather than degrading to a silent ``None``."""
        with pytest.raises(AttributeError):
            wiki_backlog_pass._lesson_promotion_backlog(_StoreWithoutPool())

    def test_raises_on_query_failure(self, monkeypatch) -> None:
        """A genuine query failure propagates to the caller's own error
        boundary (``run_wiki_maintenance``'s try/except) instead of
        being swallowed here -- the same shape as the other three
        PostgreSQL-only passes."""

        def _boom(conn):
            raise RuntimeError("PG connection reset")

        monkeypatch.setattr(
            wiki_backlog_pass, "count_lesson_promotion_candidates", _boom
        )

        with pytest.raises(RuntimeError):
            wiki_backlog_pass._lesson_promotion_backlog(_StoreWithPool())

    def test_zero_is_a_valid_result(self, monkeypatch) -> None:
        """The queue being genuinely empty is a normal 0, not an error."""
        monkeypatch.setattr(
            wiki_backlog_pass, "count_lesson_promotion_candidates", lambda conn: 0
        )

        result = wiki_backlog_pass._lesson_promotion_backlog(_StoreWithPool())

        assert result == 0
