"""Real-PG tests for grooming-health telemetry (G-4).

Covers three composition-root surfaces added for the grooming backlog/
staleness signal:
  1. ``pg_store_lesson_promotion.count_lesson_promotion_candidates`` --
     the exact (unbounded-by-limit) promotion backlog count.
  2. ``PgStatsMixin.get_grooming_ages`` -- last-executed timestamp per
     grooming kind.
  3. ``handlers.get_grooming_health`` -- the aggregate read-only tool.

All three hit the real test database (conftest.py redirects
DATABASE_URL to a disposable test DB — no mocking of SQL, per the
zetetic "tests are a sanity check on the contract" standard for
DB-backed composition roots).
"""

from __future__ import annotations

import asyncio
import time

from mcp_server.core.grooming_health import GROOMING_STALENESS_THRESHOLD_DAYS
from mcp_server.handlers import get_grooming_health
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.handlers.get_grooming_health import (
    _count_promotion_candidates as _count_candidates,
)
from mcp_server.handlers.lesson_promotion import _list_candidates


# These assertions are backend-agnostic contracts ("the count equals the
# unbounded list length", "the count rises by one after a qualifying
# rating"), so they must run against whichever dialect the resolved store
# actually is. Importing the PG functions directly bound them to one
# dialect while `get_shared_store()` returned the other, so on the SQLite
# backend they raised `unrecognized token: "@"` instead of testing the
# contract. Going through the handlers' dispatch also makes these tests
# cover the composition root the product uses (issue #220).


def count_lesson_promotion_candidates(conn) -> int:  # noqa: ARG001 - see below
    """Count via the same backend dispatch the handler uses.

    Takes and ignores `conn` so the call sites below read unchanged; the
    dispatch needs the STORE (to type-check it), not its connection.
    """
    return _count_candidates(get_shared_store())


def list_lesson_promotion_candidates(conn, limit: int = 20):  # noqa: ARG001
    """List via the same backend dispatch the handler uses."""
    return _list_candidates(get_shared_store(), limit)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestCountLessonPromotionCandidates:
    def test_matches_unbounded_list_length(self):
        """The count must equal len(list(..., limit=<very large>)) --
        same WHERE clause, this is just the aggregate form."""
        store = get_shared_store()
        count = count_lesson_promotion_candidates(store._conn)
        full_list = list_lesson_promotion_candidates(store._conn, limit=1_000_000)
        assert count == len(full_list)

    def test_increases_after_a_qualifying_lesson_is_rated_useful(self):
        from mcp_server.handlers.rate_memory import handler as rate_memory_handler
        from mcp_server.handlers.remember import handler as remember_handler

        store = get_shared_store()
        before = count_lesson_promotion_candidates(store._conn)

        marker = f"g4-count-{int(time.time() * 1000)}"
        remembered = _run(
            remember_handler(
                {
                    "content": f"[{marker}] always verify provenance before merge.",
                    "tags": ["lesson", marker],
                    "source": "self-critique",
                    "write_class": "deliberate",
                }
            )
        )
        assert remembered["stored"] is True
        lesson_id = remembered["memory_id"]

        # Structural boundary: candidates need access_count>0 OR
        # useful_count>0 (pg_store_lesson_promotion.py docstring).
        rated = _run(rate_memory_handler({"memory_id": lesson_id, "useful": True}))
        assert rated["rated"] is True

        after = count_lesson_promotion_candidates(store._conn)
        assert after == before + 1


class TestGetGroomingAges:
    def test_returns_the_three_expected_kinds(self):
        store = get_shared_store()
        ages = store.get_grooming_ages()
        assert set(ages.keys()) == {"wiki", "distillation", "promotion"}
        for v in ages.values():
            assert v is None or isinstance(v, str)

    def test_distillation_age_advances_after_a_distill_of_marker_is_written(self):
        from mcp_server.handlers.remember import handler as remember_handler

        store = get_shared_store()
        marker = f"g4-distill-of-{int(time.time() * 1000)}"

        remembered = _run(
            remember_handler(
                {
                    "content": (
                        f"[{marker}] root cause: missing transaction "
                        "boundary caused the checkout race."
                    ),
                    "tags": ["lesson", f"distill-of:{marker}"],
                    "source": "self-critique",
                    "write_class": "deliberate",
                }
            )
        )
        assert remembered["stored"] is True

        ages = store.get_grooming_ages()
        assert ages["distillation"] is not None


class TestGetGroomingHealthHandler:
    def test_response_shape(self):
        result = _run(get_grooming_health.handler({}))
        assert set(result.keys()) == {"kinds", "threshold_days", "any_stale"}
        assert set(result["kinds"].keys()) == {"wiki", "distillation", "promotion"}
        assert result["threshold_days"] == GROOMING_STALENESS_THRESHOLD_DAYS
        for kind_stats in result["kinds"].values():
            assert set(kind_stats.keys()) == {
                "backlog_count",
                "last_run_at",
                "days_since_last_run",
                "stale",
            }
            assert isinstance(kind_stats["backlog_count"], int)
            assert kind_stats["backlog_count"] >= 0

    def test_promotion_backlog_count_matches_the_indexed_count(self):
        store = get_shared_store()
        expected = count_lesson_promotion_candidates(store._conn)
        result = _run(get_grooming_health.handler({}))
        assert result["kinds"]["promotion"]["backlog_count"] == expected

    def test_never_run_kind_is_flagged_stale_with_no_age(self):
        result = _run(get_grooming_health.handler({}))
        for kind_stats in result["kinds"].values():
            if kind_stats["last_run_at"] is None:
                assert kind_stats["stale"] is True
                assert kind_stats["days_since_last_run"] is None

    def test_any_stale_is_true_iff_a_kind_is_stale(self):
        result = _run(get_grooming_health.handler({}))
        expected = any(k["stale"] for k in result["kinds"].values())
        assert result["any_stale"] == expected

    def test_never_calls_a_write_handler(self):
        """Read-only guarantee, mirroring lesson_promotion's own test:
        the module source must not reference any mutating handler."""
        import inspect

        source = inspect.getsource(get_grooming_health)
        for forbidden in (
            "add_rule.handler",
            "create_trigger.handler",
            "wiki_write.handler",
            "remember.handler",
        ):
            assert forbidden not in source


class TestSchema:
    def test_schema_is_read_only(self):
        assert get_grooming_health.schema["annotations"].get("readOnlyHint") is True

    def test_schema_has_no_required_input(self):
        assert get_grooming_health.schema["inputSchema"]["properties"] == {}
