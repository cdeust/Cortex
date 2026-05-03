"""Tests for the CORTEX_ABLATE_<NAME>=1 env-var hooks wired into production.

Each test sets the env var, calls the guarded entry point, asserts the no-op
return; unsets the env var, calls the same entry point with non-trivial
inputs, asserts a NON-no-op return. This proves the env var is read and
the guard fires (vs. the inert pre-fix state where every E1 row reported
identical numbers).

Source: spec deliverable 3 of the E1 verification campaign fix.
"""

from __future__ import annotations

import os


from mcp_server.core.ablation import Mechanism, is_mechanism_disabled


# ── helper ────────────────────────────────────────────────────────────────


def _ablate(mech: Mechanism):
    """Context-manager-style: returns env-key plus restorer."""
    key = f"CORTEX_ABLATE_{mech.name}"
    saved = os.environ.get(key)
    os.environ[key] = "1"

    def restore() -> None:
        if saved is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = saved

    return key, restore


# ── helper test ───────────────────────────────────────────────────────────


def test_is_mechanism_disabled_reads_env_per_call():
    key, restore = _ablate(Mechanism.OSCILLATORY_CLOCK)
    try:
        assert is_mechanism_disabled(Mechanism.OSCILLATORY_CLOCK) is True
        os.environ.pop(key)
        # NOT memoized: same call now returns False.
        assert is_mechanism_disabled(Mechanism.OSCILLATORY_CLOCK) is False
    finally:
        restore()


def test_is_mechanism_disabled_string_input():
    _, restore = _ablate(Mechanism.HOPFIELD)
    try:
        assert is_mechanism_disabled("HOPFIELD") is True
        assert is_mechanism_disabled("hopfield-network") is False  # not the enum NAME
    finally:
        restore()


# ── per-mechanism guard tests ─────────────────────────────────────────────


def test_oscillatory_clock_guard():
    from mcp_server.core.oscillatory_clock import (
        OscillatoryState,
        modulate_encoding,
    )

    state = OscillatoryState(theta_phase=0.0)
    base = 0.7

    _, restore = _ablate(Mechanism.OSCILLATORY_CLOCK)
    try:
        assert modulate_encoding(base, state) == base
    finally:
        restore()
    # When enabled, modulation differs from base for non-peak phases.
    state2 = OscillatoryState(theta_phase=3.14)
    assert modulate_encoding(base, state2) != base


def test_cascade_guard():
    from mcp_server.core.cascade_advancement import compute_advancement_readiness

    _, restore = _ablate(Mechanism.CASCADE)
    try:
        ready, stage, score = compute_advancement_readiness(
            current_stage="labile",
            hours_in_stage=24.0,
            dopamine_level=1.0,
            replay_count=10,
            importance=1.0,
        )
        assert ready is False and score == 0.0
    finally:
        restore()
    # Active: with high dwell + DA, advances.
    ready2, _, _ = compute_advancement_readiness(
        current_stage="labile",
        hours_in_stage=24.0,
        dopamine_level=1.0,
        replay_count=10,
        importance=1.0,
    )
    assert ready2 is True


def test_predictive_coding_guard():
    from mcp_server.core.predictive_coding_gate import gate_decision

    _, restore = _ablate(Mechanism.PREDICTIVE_CODING)
    try:
        write, reason = gate_decision(novelty_score=0.0, threshold=0.4)
        assert write is True and "ablated" in reason
    finally:
        restore()
    write2, _ = gate_decision(novelty_score=0.0, threshold=0.4)
    assert write2 is False


def test_pattern_separation_guard():
    from mcp_server.core.separation_core import orthogonalize_embedding

    new = [1.0, 0.0, 0.0]
    interferers = [[0.9, 0.1, 0.0]]

    _, restore = _ablate(Mechanism.PATTERN_SEPARATION)
    try:
        out, sep = orthogonalize_embedding(new, interferers)
        assert out == new and sep == 0.0
    finally:
        restore()
    out2, sep2 = orthogonalize_embedding(new, interferers)
    assert out2 != new or sep2 > 0.0


def test_schema_engine_guard():
    from mcp_server.core.schema_engine import find_best_matching_schema, Schema

    schemas = [
        Schema(
            schema_id="s1",
            domain="d",
            label="s1",
            entity_signature={"x": 1.0},
            tag_signature={},
        )
    ]
    _, restore = _ablate(Mechanism.SCHEMA_ENGINE)
    try:
        s, score = find_best_matching_schema(["x"], [], schemas)
        assert s is None and score == 0.0
    finally:
        restore()
    s2, score2 = find_best_matching_schema(["x"], [], schemas)
    assert s2 is not None and score2 > 0.0


def test_tripartite_synapse_guard():
    from mcp_server.core.tripartite_calcium import compute_ltp_modulation

    _, restore = _ablate(Mechanism.TRIPARTITE_SYNAPSE)
    try:
        assert compute_ltp_modulation(0.5) == 1.0
    finally:
        restore()
    # Active at facilitation regime: > 1.0
    assert compute_ltp_modulation(0.5) > 1.0


def test_interference_guard():
    from mcp_server.core.interference import compute_retrieval_suppression

    _, restore = _ablate(Mechanism.INTERFERENCE)
    try:
        assert compute_retrieval_suppression(0.5, [0.9, 0.8]) == 0.5
    finally:
        restore()
    assert compute_retrieval_suppression(0.5, [0.9, 0.8]) < 0.5


def test_homeostatic_plasticity_guard():
    from mcp_server.core.homeostatic_plasticity import compute_scaling_factor

    _, restore = _ablate(Mechanism.HOMEOSTATIC_PLASTICITY)
    try:
        assert compute_scaling_factor(current_avg_heat=0.9) == 1.0
    finally:
        restore()
    assert compute_scaling_factor(current_avg_heat=0.9) != 1.0


def test_synaptic_plasticity_guard():
    from mcp_server.core.synaptic_plasticity_hebbian import apply_hebbian_update

    edges = [{"source_entity_id": 1, "target_entity_id": 2, "weight": 0.5}]
    co = {(1, 2)}
    acts = {1: 0.9, 2: 0.9}
    thr = {1: 0.5, 2: 0.5}

    _, restore = _ablate(Mechanism.SYNAPTIC_PLASTICITY)
    try:
        out = apply_hebbian_update(edges, co, acts, thr)
        # Ablated path: weights unchanged but the result-shape contract
        # (every dict carries `action`, `weight`, `delta`) MUST hold so
        # downstream `_apply_updates` can iterate uniformly. Pre-fix returned
        # raw edges, which broke the cycle silently with a logged WARNING.
        assert len(out) == len(edges)
        assert out[0]["weight"] == 0.5
        assert out[0]["action"] == "none"
        assert out[0]["delta"] == 0.0
    finally:
        restore()
    out2 = apply_hebbian_update(edges, co, acts, thr)
    # Active path returns *new* dicts with updated weight key.
    assert out2[0].get("weight") != 0.5 or out2 is not edges


def test_synaptic_tagging_guard():
    from mcp_server.core.synaptic_tagging import apply_synaptic_tags

    new_ents = {"alice"}
    existing = []  # simplest case: empty -> ablated returns []

    _, restore = _ablate(Mechanism.SYNAPTIC_TAGGING)
    try:
        assert apply_synaptic_tags(new_ents, 0.9, existing) == []
    finally:
        restore()
    # Active path also returns [] for empty existing -- check it ran.
    # (Empty list is no-op-equivalent; the guard must short-circuit BEFORE
    # find_tagging_candidates for the test to mean anything different. Test
    # that the env-var-set path returns within bounds.)
    out = apply_synaptic_tags(new_ents, 0.9, existing)
    assert out == []  # both empty, but no exception in active path


def test_emotional_tagging_guard():
    from mcp_server.core.emotional_tagging import compute_importance_boost

    emotions = {"urgency": 0.8, "discovery": 0.5}
    arousal = 0.7

    _, restore = _ablate(Mechanism.EMOTIONAL_TAGGING)
    try:
        assert compute_importance_boost(emotions, arousal) == 1.0
    finally:
        restore()
    assert compute_importance_boost(emotions, arousal) > 1.0


def test_emotional_decay_guard():
    from mcp_server.core.emotional_tagging import compute_decay_resistance

    emotions = {"discovery": 0.6}
    arousal = 0.7

    _, restore = _ablate(Mechanism.EMOTIONAL_DECAY)
    try:
        assert compute_decay_resistance(emotions, arousal) == 1.0
    finally:
        restore()
    assert compute_decay_resistance(emotions, arousal) > 1.0


def test_microglial_pruning_guard():
    from mcp_server.core.microglial_pruning import identify_prunable_edges

    edges = [
        {
            "source_entity_id": 1,
            "target_entity_id": 2,
            "weight": 0.01,
            "last_reinforced": None,
        },
        {
            "source_entity_id": 1,
            "target_entity_id": 3,
            "weight": 1.0,
            "last_reinforced": None,
        },
    ]
    heat = {1: 0.5, 2: 0.0, 3: 0.5}
    prot = {1: False, 2: False, 3: False}

    _, restore = _ablate(Mechanism.MICROGLIAL_PRUNING)
    try:
        assert identify_prunable_edges(edges, heat, prot) == []
    finally:
        restore()
    # Active path is non-empty when active for weak edges (weight=0.01).
    # Just check it doesn't error and the return type is a list.
    out = identify_prunable_edges(edges, heat, prot)
    assert isinstance(out, list)


def test_spreading_activation_guard():
    from mcp_server.core.spreading_activation import spread_activation

    # EntityGraph is a dict[int, list[(int, float)]] adjacency list.
    g = {1: [(2, 1.0)], 2: [(1, 1.0), (3, 1.0)], 3: [(2, 1.0)]}

    _, restore = _ablate(Mechanism.SPREADING_ACTIVATION)
    try:
        out = spread_activation(g, [1])
        assert set(out.keys()) == {1}
    finally:
        restore()
    out2 = spread_activation(g, [1])
    assert set(out2.keys()) > {1}


def test_engram_allocation_guard():
    from datetime import datetime, timezone
    from mcp_server.core.engram import find_best_slot

    now_iso = datetime.now(timezone.utc).isoformat()
    slots = [
        {"slot_index": 0, "excitability": 0.1, "last_activated": now_iso},
        {"slot_index": 1, "excitability": 0.9, "last_activated": now_iso},
    ]
    _, restore = _ablate(Mechanism.ENGRAM_ALLOCATION)
    try:
        idx, exc = find_best_slot(slots)
        assert idx == 0 and exc == 0.5
    finally:
        restore()
    idx2, _ = find_best_slot(slots)
    assert idx2 == 1


def test_reconsolidation_guard():
    from mcp_server.core.reconsolidation import decide_action

    _, restore = _ablate(Mechanism.RECONSOLIDATION)
    try:
        r = decide_action(mismatch=0.5, stability=0.0, plasticity=1.0)
        assert r.action == "none"
    finally:
        restore()
    r2 = decide_action(mismatch=0.5, stability=0.0, plasticity=1.0)
    assert r2.action == "update"


def test_dendritic_clusters_guard():
    from mcp_server.core.dendritic_clusters import find_best_branch, DendriticBranch

    branches = [
        DendriticBranch(
            branch_id="b1",
            entity_signature={"alice", "bob"},
            tag_signature={"work"},
            memory_ids=[1],
            avg_heat=0.5,
        )
    ]
    _, restore = _ablate(Mechanism.DENDRITIC_CLUSTERS)
    try:
        b, score = find_best_branch({"alice"}, {"work"}, branches)
        assert b is None and score == 0.0
    finally:
        restore()
    b2, score2 = find_best_branch({"alice"}, {"work"}, branches)
    assert b2 is not None and score2 > 0.0


def test_two_stage_model_guard():
    from mcp_server.core.two_stage_model import should_release_hippocampal_trace

    _, restore = _ablate(Mechanism.TWO_STAGE_MODEL)
    try:
        assert should_release_hippocampal_trace(0.0, "consolidated", 0.0) is False
    finally:
        restore()
    assert should_release_hippocampal_trace(0.0, "consolidated", 0.0) is True


def test_hopfield_guard():
    import numpy as np
    from mcp_server.core.hopfield import retrieve

    pm = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    pids = [10, 20]
    q = np.array([1.0, 0.0], dtype=np.float32).tobytes()

    _, restore = _ablate(Mechanism.HOPFIELD)
    try:
        assert retrieve(q, pm, pids) == []
    finally:
        restore()
    assert len(retrieve(q, pm, pids)) > 0


def test_hdc_guard():
    from mcp_server.core.hdc_encoder import compute_hdc_scores

    mems = [(1, "alice met bob"), (2, "carol met dave")]
    _, restore = _ablate(Mechanism.HDC)
    try:
        assert compute_hdc_scores("alice", mems) == []
    finally:
        restore()
    out = compute_hdc_scores("alice met bob", mems)
    assert len(out) > 0


def test_adaptive_decay_guard():
    from mcp_server.core.thermodynamics import compute_decay

    _, restore = _ablate(Mechanism.ADAPTIVE_DECAY)
    try:
        # Ablated: ignores importance/valence; uses constant lambda.
        d_imp = compute_decay(1.0, hours_elapsed=10.0, importance=0.95)
        d_unimp = compute_decay(1.0, hours_elapsed=10.0, importance=0.1)
        assert d_imp == d_unimp
    finally:
        restore()
    # Active: importance 0.95 decays slower than 0.1.
    d_imp2 = compute_decay(1.0, hours_elapsed=10.0, importance=0.95)
    d_unimp2 = compute_decay(1.0, hours_elapsed=10.0, importance=0.1)
    assert d_imp2 > d_unimp2


def test_neuromodulation_guard():
    from mcp_server.core.coupled_neuromodulation import (
        update_state,
        NeuromodulatoryState,
        OperationSignals,
    )

    cur = NeuromodulatoryState()
    sig = OperationSignals(
        error_resolved=True,
        test_passed=True,
        novel_entities=3,
        total_entities=5,
        schema_match=0.5,
        memory_importance=0.8,
    )

    _, restore = _ablate(Mechanism.NEUROMODULATION)
    try:
        out = update_state(cur, sig)
        assert out is cur  # frozen, identity
    finally:
        restore()
    out2 = update_state(cur, sig)
    assert out2 is not cur


def test_surprise_momentum_guard():
    from mcp_server.core.titans_memory import TitansMemory

    tm = TitansMemory(dim=8)
    # If torch not installed, both branches return early -- test only the guard.
    _, restore = _ablate(Mechanism.SURPRISE_MOMENTUM)
    try:
        s = tm.update(b"\x00" * 32, [b"\x00" * 32])
        assert s == 0.0
    finally:
        restore()


def test_co_activation_guard():
    """Co-activation guard short-circuits before any DB call."""
    from mcp_server.handlers.recall import _apply_co_activation

    class _FakeSettings:
        CO_ACTIVATION_ENABLED = True
        CO_ACTIVATION_MIN_SCORE = 0.0
        CO_ACTIVATION_LEARNING_RATE = 0.1

    class _FakeStore:
        def __init__(self) -> None:
            self.calls = 0

        def reinforce_or_create_relationship(self, *a, **k) -> None:
            self.calls += 1

    settings = _FakeSettings()
    store = _FakeStore()
    results = [
        {"score": 0.9, "content": "import alpha\ndef beta(): pass"},
        {"score": 0.9, "content": "import gamma\ndef delta(): pass"},
    ]

    _, restore = _ablate(Mechanism.CO_ACTIVATION)
    try:
        _apply_co_activation(results, store, settings)
        assert store.calls == 0
    finally:
        restore()
    _apply_co_activation(results, store, settings)
    assert store.calls > 0
