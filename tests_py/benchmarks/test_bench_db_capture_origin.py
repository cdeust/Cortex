"""benchmarks.lib.bench_db._apply_capture_origin_mix (issue #368 harness fix).

Contract under test: BenchmarkDB.load_memories no longer lets every memory
fall through to insert_memory's "unknown" default — each memory lacking an
explicit capture_origin is stamped with one drawn from the measured
production mixture, and a memory that already sets its own origin (e.g. the
adversarial corpus) is left alone.

Requires no live PostgreSQL: the assignment logic is a pure list mutation,
extracted specifically so it is testable without BenchmarkDB.open(). It DOES
require the `psycopg` driver to be installed, because `benchmarks/lib/
bench_db.py` hard-imports `PgMemoryStore` at module level (established
convention — see `tests_py/benchmarks/test_lib_init_no_psycopg.py`); this
module therefore importorskips exactly like `tests_py/integration/
test_recall_trust_ranking.py` does, so it skips cleanly on the SQLite-only
CI lane instead of failing collection.
"""

from __future__ import annotations

import pytest

pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

from benchmarks.lib.bench_db import _apply_capture_origin_mix  # noqa: E402
from mcp_server.core.capture_origin import ALL_ORIGINS  # noqa: E402


class TestApplyCaptureOriginMix:
    def test_stamps_every_memory_missing_the_field(self):
        memories = [{"content": f"memory {i}"} for i in range(200)]
        _apply_capture_origin_mix(memories)
        assert all("capture_origin" in m for m in memories)
        assert all(m["capture_origin"] in ALL_ORIGINS for m in memories)

    def test_never_overwrites_an_explicit_origin(self):
        memories = [
            {"content": "adversarial", "capture_origin": "network"},
            {"content": "legit", "capture_origin": "deliberate"},
            {"content": "unset"},
        ]
        _apply_capture_origin_mix(memories)
        assert memories[0]["capture_origin"] == "network"
        assert memories[1]["capture_origin"] == "deliberate"
        assert memories[2]["capture_origin"] in ALL_ORIGINS

    def test_at_scale_produces_a_mixture_not_a_constant(self):
        memories = [{"content": f"memory {i}"} for i in range(3000)]
        _apply_capture_origin_mix(memories)
        origins_seen = {m["capture_origin"] for m in memories}
        assert len(origins_seen) > 1
        assert "network" in origins_seen  # the untrusted-at-read minority

    def test_empty_list_is_a_no_op(self):
        memories: list[dict] = []
        _apply_capture_origin_mix(memories)
        assert memories == []
