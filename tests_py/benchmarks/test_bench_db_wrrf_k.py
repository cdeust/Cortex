"""benchmarks.lib.bench_db.BenchmarkDB.recall forwards the WRRF constant.

Contract under test: the benchmark recall path takes ``wrrf_k`` from the same
settings accessor the production handler uses, so ``CORTEX_MEMORY_WRRF_K``
changes what a benchmark measures. Before this contract, ``BenchmarkDB.recall``
never passed ``wrrf_k`` and ``pg_recall.recall`` fell back to its default of
60, which made any k sweep run through the harness return identical scores
for every k.

Requires no live PostgreSQL: the store and embeddings are placeholders and
``pg_recall`` is replaced by a spy. It does need the ``psycopg`` driver
because ``benchmarks/lib/bench_db.py`` hard-imports ``PgMemoryStore`` at
module level, so it skips on the SQLite-only lane like its neighbours.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

from benchmarks.lib import bench_db  # noqa: E402


def _recall_with_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def spy(**kwargs: Any) -> list[dict[str, Any]]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(bench_db, "pg_recall", spy)
    db = bench_db.BenchmarkDB(database_url="postgresql://unused")
    db._store = object()  # type: ignore[assignment]  # placeholder, never used by the spy
    db._embeddings = object()  # type: ignore[assignment]  # placeholder, never used by the spy
    db.recall("any query")
    return seen


def test_env_override_reaches_pg_recall(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORTEX_MEMORY_WRRF_K", "17")
    assert _recall_with_spy(monkeypatch)["wrrf_k"] == 17


def test_default_matches_the_production_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CORTEX_MEMORY_WRRF_K", raising=False)
    assert _recall_with_spy(monkeypatch)["wrrf_k"] == 60  # source: memory_config.WRRF_K
