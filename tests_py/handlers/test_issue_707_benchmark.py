"""100k-row single-process collapse measurement requested in PR #827 review.

The fixture contains 100000 distinct facts followed by 100 copies of one fact.
Durations are observations, never timing-based pass/fail thresholds.
"""

from __future__ import annotations

from time import perf_counter

from mcp_server.infrastructure.memory_exact import collapse_exact
from tests_py.handlers.test_issue_707_exact_duplicates import store as store


def test_exact_collapse_100k_measurement(store):
    content = "exact benchmark corpus"
    with store._conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO memories (content) VALUES (%s)",
            ((f"{content} {index}",) for index in range(100000)),
        )
    store._conn.commit()
    started = perf_counter()
    assert collapse_exact(store) == {"superseded_total": 0}
    quiet_seconds = perf_counter() - started
    with store._conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO memories (content) VALUES (%s)",
            ((f"{content} 0",) for _ in range(100)),
        )
    store._conn.commit()
    started = perf_counter()
    assert collapse_exact(store) == {"superseded_total": 100}
    duplicate_seconds = perf_counter() - started
    assert collapse_exact(store) == {"superseded_total": 0}
    backend = type(store).__name__
    print(
        f"EXACT_BENCHMARK backend={backend} rows=100000 duplicate_copies=100 "
        f"quiet_seconds={quiet_seconds} duplicate_seconds={duplicate_seconds}"
    )
