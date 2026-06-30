"""Live-PG behavior tests for the A3 decay-clock anchor in insert_memory.

Root cause (benchmark module #6 campaign, 2026-06-30): ``insert_memory``
let ``heat_base_set_at`` take its schema DEFAULT NOW(), so a
historical-dated insert (an imported 2023 conversation, a benchmark
haystack with multi-year timestamps) read ``hours_elapsed ≈ 0`` in
``effective_heat()`` and the SQL forgetting law never engaged —
``effective_heat ≡ heat_base`` regardless of decay law.

The fix anchors ``heat_base_set_at`` to the event date (``created_at``)
on insert. ``effective_heat()`` decays from
``COALESCE(heat_base_set_at, last_accessed, created_at)``; for a
never-touched insert the faithful "last canonical touch" IS the event,
so the clock now reads real elapsed time.

These tests pin the two invariants of that fix:
  - INV-FRESH: a fresh insert (created_at ≈ now) is a no-op —
    effective_heat == heat_base (hours_elapsed ≈ 0).
  - INV-AGED: a historical-dated insert engages the law —
    effective_heat < heat_base (hours_elapsed > 0).

Runs against cortex_test (conftest redirects DATABASE_URL).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mcp_server.infrastructure.pg_store import PgMemoryStore
from tests_py.conftest import _USE_PG  # type: ignore

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — decay clock needs live schema"
)

_DOMAIN = "decay-clock-anchor-test"


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    try:
        s._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
        s._conn.commit()
    finally:
        s.close()


def _effective_heat(store: PgMemoryStore, memory_id: int) -> float:
    row = store._execute(
        "SELECT effective_heat(m, NOW(), 1.0) AS eff FROM memories m WHERE id = %s",
        (memory_id,),
    ).fetchone()
    assert row is not None
    return float(row["eff"])


def _hours_elapsed(store: PgMemoryStore, memory_id: int) -> float:
    row = store._execute(
        "SELECT EXTRACT(EPOCH FROM (NOW() - heat_base_set_at)) / 3600.0 AS hrs "
        "FROM memories WHERE id = %s",
        (memory_id,),
    ).fetchone()
    assert row is not None
    return float(row["hrs"])


def test_fresh_insert_is_decay_noop(store: PgMemoryStore) -> None:
    """INV-FRESH: created_at ≈ now ⇒ clock ≈ now ⇒ effective_heat == heat_base."""
    mid = store.insert_memory(
        {
            "content": "fresh memory, no historical date",
            "heat": 1.0,
            "domain": _DOMAIN,
            "is_benchmark": True,
        }
    )
    assert _hours_elapsed(store, mid) < 1.0
    assert _effective_heat(store, mid) == pytest.approx(1.0, abs=1e-3)


def test_historical_insert_engages_forgetting_law(store: PgMemoryStore) -> None:
    """INV-AGED: a year-old created_at backdates the clock ⇒ law decays heat."""
    old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    mid = store.insert_memory(
        {
            "content": "imported 2023 conversation",
            "heat": 1.0,
            "domain": _DOMAIN,
            "is_benchmark": True,
            "created_at": old,
        }
    )
    # ~8760h must have elapsed on the decay clock, not ≈ 0.
    assert _hours_elapsed(store, mid) > 8000.0
    # The SQL forgetting law must have pulled effective_heat strictly below
    # the stored heat_base. (Exact value depends on stage/law constants;
    # this test pins only that the clock engages, not the law family.)
    assert _effective_heat(store, mid) < 1.0


def test_explicit_heat_base_set_at_overrides_created_at(store: PgMemoryStore) -> None:
    """An explicit heat_base_set_at wins over created_at (e.g. re-anchoring)."""
    old_created = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    recent_anchor = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    mid = store.insert_memory(
        {
            "content": "old event, recently re-anchored",
            "heat": 1.0,
            "domain": _DOMAIN,
            "is_benchmark": True,
            "created_at": old_created,
            "heat_base_set_at": recent_anchor,
        }
    )
    # Clock reads the explicit anchor (≈1h), not the 365-day created_at.
    assert _hours_elapsed(store, mid) < 24.0
