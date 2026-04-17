"""A3 step 7: flag-gated decay cycle regression test.

Asserts:
    - flag=false → legacy eager path (memories_decayed can be > 0)
    - flag=true  → lazy path (memories_decayed = 0, reason_for_zero set)

Rationale:
    The A3 lazy-heat design (docs/program/phase-3-a3-migration-design.md
    §6) removes per-row heat writes from the decay cycle, replacing
    them with read-time computation in ``effective_heat()``. This test
    guards the behavior contract at the Python boundary before the
    schema migration is applied — i.e., the flag dispatcher works in
    isolation even without the PL/pgSQL function installed.

    Entity decay is out of scope for A3 (D2 program), so
    ``entities_decayed`` is not asserted on — behavior unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_server.handlers.consolidation.decay import run_decay_cycle


class _SettingsStub:
    DECAY_FACTOR = 0.95
    IMPORTANCE_DECAY_FACTOR = 0.99
    EMOTIONAL_DECAY_RESISTANCE = 0.5
    COLD_THRESHOLD = 0.05


def _memory(mid: int, heat: float = 0.5, stage: str = "labile") -> dict:
    return {
        "id": mid,
        "heat": heat,
        "consolidation_stage": stage,
        "emotional_valence": 0.0,
        "importance": 0.5,
        "access_count": 1,
        "is_protected": False,
        "last_accessed": None,
        "stage_entered_at": None,
        "created_at": None,
        "domain": "default",
    }


@pytest.fixture
def stub_store():
    store = MagicMock()
    store.get_all_memories_for_decay.return_value = [
        _memory(1, heat=0.8),
        _memory(2, heat=0.6),
    ]
    # Decay writes a batch, entity decay returns an empty list.
    store.update_memories_heat_batch.return_value = 2
    store.get_all_entities.return_value = []
    store.update_entities_heat_batch.return_value = 0
    return store


def test_legacy_eager_path_when_flag_false(monkeypatch, stub_store):
    """flag=false: decay writes per-row heats, mode='legacy_eager'."""
    from mcp_server.infrastructure import memory_config

    settings = memory_config.get_memory_settings()
    monkeypatch.setattr(settings, "A3_LAZY_HEAT", False, raising=False)

    result = run_decay_cycle(stub_store, _SettingsStub())

    assert result["mode"] == "legacy_eager"
    assert "reason_for_zero" not in result
    # Legacy path calls the batch writer (primary decay + metabolic).
    assert stub_store.update_memories_heat_batch.call_count >= 1


def test_a3_lazy_path_when_flag_true(monkeypatch, stub_store):
    """flag=true: no per-row writes, mode='a3_lazy', reason_for_zero set."""
    from mcp_server.infrastructure import memory_config

    settings = memory_config.get_memory_settings()
    monkeypatch.setattr(settings, "A3_LAZY_HEAT", True, raising=False)

    result = run_decay_cycle(stub_store, _SettingsStub())

    assert result["mode"] == "a3_lazy"
    assert result["memories_decayed"] == 0
    assert result["metabolic_updates"] == 0
    assert result["reason_for_zero"] == "lazy_decay_via_effective_heat"
    # Critical: the batch writer must NOT be called in lazy mode.
    stub_store.update_memories_heat_batch.assert_not_called()
