"""Tests for mcp_server.core.decay_cycle — entity heat decay.

Memory heat decay is covered separately by the SQL-side
``effective_heat()`` tests (``tests_py/infrastructure/test_pg_alpha_integral.py``,
``test_pg_effective_stage_parity.py``, ``test_pg_decay_clock_anchor.py``) —
see decay_cycle.py's module docstring and issue #346 for why the
Python-side per-row memory decay path (including its ACT-R alternative)
was removed rather than kept as untested reference code.
"""

from datetime import datetime, timezone, timedelta

from mcp_server.core.decay_cycle import compute_entity_decay


class TestComputeEntityDecay:
    def test_recent_entities_no_decay(self):
        now = datetime.now(timezone.utc)
        entities = [{"id": 1, "heat": 0.8, "last_accessed": now.isoformat()}]
        updates = compute_entity_decay(entities, now=now)
        assert len(updates) == 0

    def test_old_entities_decay(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=48)).isoformat()
        entities = [{"id": 1, "heat": 0.8, "last_accessed": old}]
        updates = compute_entity_decay(entities, now=now)
        assert len(updates) == 1
        assert updates[0][1] < 0.8

    def test_cold_entities_skipped(self):
        now = datetime.now(timezone.utc)
        entities = [{"id": 1, "heat": 0.01, "last_accessed": now.isoformat()}]
        updates = compute_entity_decay(entities, now=now, cold_threshold=0.05)
        assert len(updates) == 0
