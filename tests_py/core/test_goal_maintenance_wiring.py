"""Wiring tests for A3 goal / task-set maintenance.

Verifies the sustained goal vector re-weights (a) the write-gate novelty and
(b) the recall fusion score while a goal is active, that no active goal is a
strict identity on both paths, and that the ablation guard disables the
mechanism.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")

from mcp_server.core import goal_maintenance as gm
from mcp_server.core import write_gate
from mcp_server.core.recall_pipeline import goal_maintenance_rerank


# ── Fake store exposing get_active_prospective_memories ──────────────────────
class _GoalStore:
    """Minimal store stub exposing only the prospective-trigger reader used by
    the A3 defensive readers (write_gate.read_active_goal / pg_recall._get_
    active_goal)."""

    def __init__(self, triggers):
        self._triggers = triggers

    def get_active_prospective_memories(self):
        return self._triggers


_GOAL_TRIGGERS = [
    {"trigger_type": "keyword_match", "trigger_condition": "recall pipeline latency"}
]


# ── write_gate.read_active_goal (the promotion step) ─────────────────────────
class TestReadActiveGoal:
    def test_none_store_gives_empty_goal(self):
        assert write_gate.read_active_goal(None) is gm.EMPTY_GOAL

    def test_store_without_reader_gives_empty_goal(self):
        assert write_gate.read_active_goal(object()) is gm.EMPTY_GOAL

    def test_store_with_no_triggers_gives_empty_goal(self):
        assert write_gate.read_active_goal(_GoalStore([])) is gm.EMPTY_GOAL

    def test_triggers_promoted_to_active_goal(self):
        goal = write_gate.read_active_goal(_GoalStore(_GOAL_TRIGGERS))
        assert gm.goal_vector_is_active(goal)
        assert "recall" in goal.keywords and "pipeline" in goal.keywords

    def test_reader_exception_is_non_fatal(self):
        class _Boom:
            def get_active_prospective_memories(self):
                raise RuntimeError("db down")

        assert write_gate.read_active_goal(_Boom()) is gm.EMPTY_GOAL


# ── Write-gate wiring: apply_goal_maintenance ────────────────────────────────
class TestWriteGateWiring:
    def teardown_method(self):
        os.environ.pop("CORTEX_ABLATE_GOAL_MAINTENANCE", None)

    def test_no_active_goal_is_identity(self):
        # store with no triggers => no goal => novelty unchanged, info None
        score, info = write_gate.apply_goal_maintenance(
            0.5, "the recall pipeline", ["E"], _GoalStore([])
        )
        assert score == 0.5
        assert info is None

    def test_none_store_is_identity(self):
        score, info = write_gate.apply_goal_maintenance(0.5, "content", [], None)
        assert score == 0.5 and info is None

    def test_goal_relevant_input_gets_boost(self):
        store = _GoalStore(_GOAL_TRIGGERS)
        # content matches 2 of 3 goal keywords (recall, pipeline)
        score, info = write_gate.apply_goal_maintenance(
            0.5, "the recall pipeline is slow", [], store
        )
        assert score > 0.5  # favored
        assert info is not None
        assert info["relevance"] > 0.0
        assert info["gain"] > 1.0

    def test_fully_relevant_input_gets_full_boost(self):
        store = _GoalStore(_GOAL_TRIGGERS)
        score, info = write_gate.apply_goal_maintenance(
            0.5, "recall pipeline latency numbers", [], store
        )
        # all 3 keywords present => relevance 1.0 => gain 1 + weight
        assert abs(info["gain"] - (1.0 + gm.GOAL_WRITE_WEIGHT)) < 1e-9
        assert abs(score - 0.5 * (1.0 + gm.GOAL_WRITE_WEIGHT)) < 1e-9

    def test_off_task_input_under_active_goal_is_unchanged(self):
        store = _GoalStore(_GOAL_TRIGGERS)
        score, info = write_gate.apply_goal_maintenance(
            0.5, "completely unrelated stuff", [], store
        )
        assert score == 0.5  # relevance 0 => gain 1.0
        assert info is None  # goal active but no relevance => treated as no-op

    def test_modulated_novelty_clamped_to_one(self):
        store = _GoalStore(_GOAL_TRIGGERS)
        score, info = write_gate.apply_goal_maintenance(
            0.98, "recall pipeline latency", [], store
        )
        assert score <= 1.0

    def test_ablation_guard_disables(self):
        os.environ["CORTEX_ABLATE_GOAL_MAINTENANCE"] = "1"
        store = _GoalStore(_GOAL_TRIGGERS)
        score, info = write_gate.apply_goal_maintenance(
            0.5, "recall pipeline latency", [], store
        )
        assert score == 0.5 and info is None


# ── Recall wiring: goal_maintenance_rerank ───────────────────────────────────
def _cands():
    return [
        {"memory_id": "m1", "content": "note about the weather", "score": 0.60},
        {
            "memory_id": "m2",
            "content": "the recall pipeline latency fix",
            "score": 0.55,
        },
    ]


class TestRecallWiring:
    def teardown_method(self):
        os.environ.pop("CORTEX_ABLATE_GOAL_MAINTENANCE", None)

    def test_no_active_goal_is_identity(self):
        cands = _cands()
        out = goal_maintenance_rerank(cands, gm.EMPTY_GOAL)
        assert [c["memory_id"] for c in out] == ["m1", "m2"]
        assert out[0]["score"] == 0.60 and out[1]["score"] == 0.55

    def test_none_goal_is_identity(self):
        cands = _cands()
        out = goal_maintenance_rerank(cands, None)
        assert [c["memory_id"] for c in out] == ["m1", "m2"]

    def test_active_goal_boosts_relevant_candidate(self):
        goal = gm.build_goal_from_task("recall pipeline latency")
        cands = _cands()
        out = goal_maintenance_rerank(cands, goal)
        # m2 is goal-relevant → boosted above m1 despite lower base score
        assert out[0]["memory_id"] == "m2"
        assert out[0]["score"] > 0.55  # boosted
        # m1 off-task → unchanged
        m1 = next(c for c in out if c["memory_id"] == "m1")
        assert m1["score"] == 0.60

    def test_off_task_set_unchanged_in_order(self):
        goal = gm.build_goal_from_task("astrophysics supernova")
        cands = _cands()
        out = goal_maintenance_rerank(cands, goal)
        # neither candidate matches the goal → order and scores preserved
        assert [c["memory_id"] for c in out] == ["m1", "m2"]
        assert out[0]["score"] == 0.60 and out[1]["score"] == 0.55

    def test_single_candidate_is_noop(self):
        goal = gm.build_goal_from_task("recall pipeline")
        cands = [{"memory_id": "m1", "content": "recall pipeline", "score": 0.5}]
        out = goal_maintenance_rerank(cands, goal)
        assert out[0]["score"] == 0.5  # <2 candidates → untouched

    def test_ablation_guard_disables(self):
        os.environ["CORTEX_ABLATE_GOAL_MAINTENANCE"] = "1"
        goal = gm.build_goal_from_task("recall pipeline latency")
        cands = _cands()
        out = goal_maintenance_rerank(cands, goal)
        assert [c["memory_id"] for c in out] == ["m1", "m2"]
        assert out[1]["score"] == 0.55  # unchanged
