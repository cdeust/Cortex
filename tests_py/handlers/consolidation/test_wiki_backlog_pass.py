"""Unit tests for handlers.consolidation.wiki_backlog_pass's G-2 grooming
addition (2026-07-11): the lesson_promotion backlog count report.

Monkeypatch-based — the coverage/cluster/drift audits this module also
runs touch the real filesystem WIKI_ROOT and are out of scope here;
this file isolates the one new mechanical field.
"""

from __future__ import annotations

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

    def test_degrades_to_none_when_store_lacks_batch_pool(self) -> None:
        # No monkeypatch of the count function needed — the AttributeError
        # on `.batch_pool` fires before it would ever be called.
        result = wiki_backlog_pass._lesson_promotion_backlog(_StoreWithoutPool())

        assert result is None

    def test_degrades_to_none_on_query_failure(self, monkeypatch) -> None:
        def _boom(conn):
            raise RuntimeError("PG connection reset")

        monkeypatch.setattr(
            wiki_backlog_pass, "count_lesson_promotion_candidates", _boom
        )

        result = wiki_backlog_pass._lesson_promotion_backlog(_StoreWithPool())

        assert result is None

    def test_zero_is_a_valid_distinct_result_from_none(self, monkeypatch) -> None:
        """None means 'query failed'; 0 means 'queue is genuinely empty' —
        callers must be able to tell these apart."""
        monkeypatch.setattr(
            wiki_backlog_pass, "count_lesson_promotion_candidates", lambda conn: 0
        )

        result = wiki_backlog_pass._lesson_promotion_backlog(_StoreWithPool())

        assert result == 0
        assert result is not None
