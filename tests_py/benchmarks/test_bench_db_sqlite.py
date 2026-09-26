"""BenchmarkDB SQLite mode: real store, production ingestion and recall.

Contracts under test:
  1. SQLite mode ingests a mini corpus through the production path and recall
     returns the matching memory.
  2. ``CORTEX_MEMORY_WRRF_K`` changes the fused scores on SQLite, where the
     rank-based RRF ``weight/(k+rank)`` really uses k (on PostgreSQL k only
     scales the agent-topic bonus).
  3. Closing removes the throwaway database file; PostgreSQL stays the default.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

pytest.importorskip("sqlite_vec", reason="sqlite-vec not installed ([sqlite] extra)")

from benchmarks.lib import bench_db  # noqa: E402
from benchmarks.lib.bench_backend import resolve_backend  # noqa: E402

_CORPUS = [
    {"content": "The user adopted a greyhound named Biscuit from a shelter in March."},
    {"content": "Quarterly tax filing is due on the fifteenth of the month."},
    {"content": "The user prefers dark roast coffee brewed with a French press."},
    {"content": "A marathon training plan starts with a long run every Sunday."},
]


@pytest.fixture(autouse=True)
def _fresh_settings():
    from mcp_server.infrastructure.memory_config import get_memory_settings

    get_memory_settings.cache_clear()
    yield
    get_memory_settings.cache_clear()


def _fused_scores(k: int, monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Scores returned by the store's fused first stage, before the pipeline's
    later stages (which re-rank with their own constants) touch them."""
    monkeypatch.setenv("CORTEX_MEMORY_WRRF_K", str(k))
    from mcp_server.infrastructure.memory_config import get_memory_settings

    get_memory_settings.cache_clear()
    captured: list[float] = []
    with bench_db.BenchmarkDB(backend="sqlite") as db:
        db.load_memories([dict(m) for m in _CORPUS], domain="mini")
        store = db._store
        original = store.recall_memories

        def spy(**kwargs: Any) -> list[dict[str, Any]]:
            rows = original(**kwargs)
            captured.extend(float(r["score"]) for r in rows)
            return rows

        monkeypatch.setattr(store, "recall_memories", spy)
        db.recall("greyhound adopted from a shelter", domain="mini", rerank=False)
    return captured


def test_sqlite_mode_returns_matching_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORTEX_MEMORY_WRRF_K", raising=False)
    with bench_db.BenchmarkDB(backend="sqlite") as db:
        db.load_memories([dict(m) for m in _CORPUS], domain="mini")
        rows: list[dict[str, Any]] = db.recall(
            "greyhound adopted from a shelter", domain="mini", rerank=False
        )
    assert rows and "greyhound" in rows[0]["content"]


def test_wrrf_k_does_not_change_sqlite_fused_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    low = _fused_scores(10, monkeypatch)
    high = _fused_scores(200, monkeypatch)
    assert low and high
    assert low == pytest.approx(high)


def test_close_removes_throwaway_file() -> None:
    db = bench_db.BenchmarkDB(backend="sqlite").open()
    assert db._sqlite is not None
    directory = db._sqlite.directory
    assert os.path.isdir(directory)
    db.close()
    assert not os.path.exists(directory)


def test_postgresql_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORTEX_BENCH_BACKEND", raising=False)
    assert resolve_backend(None) == "postgresql"
    monkeypatch.setenv("CORTEX_BENCH_BACKEND", "sqlite")
    assert resolve_backend(None) == "sqlite"
    with pytest.raises(ValueError):
        resolve_backend("mysql")
