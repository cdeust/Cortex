"""Unit tests for A3 goal / task-set maintenance (core.goal_maintenance).

Covers: promoting prospective triggers into a sustained goal vector,
goal-relevance scoring, the write/recall re-weight nudges, and the
behavior-preserving no-active-goal identity path.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from mcp_server.core import goal_maintenance as gm


# ── GoalVector construction from prospective triggers ─────────────────────────
class TestBuildFromTriggers:
    def test_empty_or_none_triggers_yield_inactive_empty_goal(self):
        assert gm.build_goal_from_triggers(None) is gm.EMPTY_GOAL
        assert gm.build_goal_from_triggers([]) is gm.EMPTY_GOAL
        assert not gm.goal_vector_is_active(gm.EMPTY_GOAL)

    def test_is_active_on_any_single_signal_alone(self):
        # Each feature family alone must be sufficient (a plain `or` chain,
        # not `keywords or (entities and directories)` — issue #282
        # mutation-testing gap: an entities-only goal with no directories
        # was previously indistinguishable from an `and`-combined mutant).
        assert gm.goal_vector_is_active(gm.GoalVector(entities=frozenset({"e"})))
        assert gm.goal_vector_is_active(gm.GoalVector(directories=("d",)))
        assert gm.goal_vector_is_active(gm.GoalVector(keywords=frozenset({"k"})))

    def test_keyword_trigger_becomes_goal_keywords(self):
        triggers = [
            {
                "trigger_type": "keyword_match",
                "trigger_condition": "refactor recall pipeline",
            }
        ]
        goal = gm.build_goal_from_triggers(triggers)
        assert gm.goal_vector_is_active(goal)
        assert "refactor" in goal.keywords
        assert "recall" in goal.keywords
        assert "pipeline" in goal.keywords

    def test_keyword_extraction_matches_prospective_filter(self):
        # short tokens (<3) and stop words dropped, mirroring prospective.py
        triggers = [
            {"trigger_type": "keyword_match", "trigger_condition": "the fix db and io"}
        ]
        goal = gm.build_goal_from_triggers(triggers)
        assert "the" not in goal.keywords  # stop word
        assert "and" not in goal.keywords  # stop word
        assert "io" not in goal.keywords  # too short
        assert "fix" in goal.keywords

    def test_entity_trigger_becomes_goal_entity_lowercased(self):
        triggers = [
            {"trigger_type": "entity_match", "trigger_condition": "PgMemoryStore"}
        ]
        goal = gm.build_goal_from_triggers(triggers)
        assert "pgmemorystore" in goal.entities

    def test_directory_trigger_uses_target_directory(self):
        triggers = [
            {
                "trigger_type": "directory_match",
                "trigger_condition": "",
                "target_directory": "/repo/Cortex/mcp_server",
            }
        ]
        goal = gm.build_goal_from_triggers(triggers)
        assert goal.directories == ("/repo/cortex/mcp_server",)

    def test_directory_trigger_falls_back_to_condition(self):
        triggers = [
            {"trigger_type": "directory_match", "trigger_condition": "/repo/Cortex"}
        ]
        goal = gm.build_goal_from_triggers(triggers)
        assert goal.directories == ("/repo/cortex",)

    def test_time_based_trigger_contributes_nothing(self):
        triggers = [{"trigger_type": "time_based", "trigger_condition": "09:30"}]
        goal = gm.build_goal_from_triggers(triggers)
        assert goal is gm.EMPTY_GOAL

    def test_mixed_triggers_merge_across_families(self):
        triggers = [
            {"trigger_type": "keyword_match", "trigger_condition": "optimize query"},
            {"trigger_type": "entity_match", "trigger_condition": "Postgres"},
            {"trigger_type": "directory_match", "target_directory": "/db"},
            {"trigger_type": "time_based", "trigger_condition": "10:00"},
        ]
        goal = gm.build_goal_from_triggers(triggers, label="db work")
        assert goal.keywords == frozenset({"optimize", "query"})
        assert goal.entities == frozenset({"postgres"})
        assert goal.directories == ("/db",)
        assert goal.label == "db work"

    def test_triggers_with_only_noise_yield_empty_goal(self):
        # keyword trigger whose only tokens are stop/short → no goal signal
        triggers = [{"trigger_type": "keyword_match", "trigger_condition": "the a an"}]
        assert gm.build_goal_from_triggers(triggers) is gm.EMPTY_GOAL


class TestBuildFromTask:
    def test_task_string_becomes_keywords(self):
        goal = gm.build_goal_from_task("investigate heat decay bug")
        assert gm.goal_vector_is_active(goal)
        assert "investigate" in goal.keywords
        assert "decay" in goal.keywords
        assert goal.label == "investigate heat decay bug"

    def test_task_with_entities_and_directory(self):
        goal = gm.build_goal_from_task(
            "trace calls", entities=["WriteGate"], directory="/src"
        )
        assert "trace" in goal.keywords
        assert "writegate" in goal.entities
        assert goal.directories == ("/src",)

    def test_empty_task_yields_empty_goal(self):
        assert gm.build_goal_from_task("") is gm.EMPTY_GOAL
        assert (
            gm.build_goal_from_task("   ", entities=[], directory="") is gm.EMPTY_GOAL
        )


# ── Goal relevance scoring ────────────────────────────────────────────────────
class TestGoalRelevance:
    def test_inactive_goal_scores_zero(self):
        assert gm.goal_relevance(gm.EMPTY_GOAL, "anything at all") == 0.0

    def test_full_keyword_match_scores_one(self):
        goal = gm.build_goal_from_task("recall pipeline")
        # both goal keywords present in content
        assert gm.goal_relevance(goal, "the recall pipeline is slow") == 1.0

    def test_partial_keyword_match_is_fractional(self):
        goal = gm.build_goal_from_task("recall pipeline latency")  # 3 keywords
        score = gm.goal_relevance(goal, "the recall stage")  # 1 of 3
        assert abs(score - 1.0 / 3.0) < 1e-9

    def test_no_overlap_scores_zero(self):
        goal = gm.build_goal_from_task("recall pipeline")
        assert gm.goal_relevance(goal, "completely unrelated content") == 0.0

    def test_keyword_match_is_word_boundary_not_substring(self):
        # goal keyword "ask" must not fire on "task"
        goal = gm.build_goal_from_task("ask questions")
        assert gm.goal_relevance(goal, "this task is done") == 0.0

    def test_entity_overlap_scores(self):
        goal = gm.build_goal_from_task("work", entities=["PgMemoryStore"])
        assert (
            gm.goal_relevance(goal, "some text", entities=["PgMemoryStore", "Other"])
            == 1.0
        )
        assert gm.goal_relevance(goal, "some text", entities=["Nope"]) == 0.0

    def test_directory_match_scores(self):
        goal = gm.build_goal_from_task("work", directory="/repo/core")
        assert gm.goal_relevance(goal, "x", directory="/repo/core/pg_recall.py") == 1.0
        assert gm.goal_relevance(goal, "x", directory="/elsewhere") == 0.0

    def test_relevance_is_max_across_families(self):
        # keyword miss but entity hit → still full relevance
        goal = gm.build_goal_from_task("nomatchword", entities=["Target"])
        assert gm.goal_relevance(goal, "no relevant tokens", entities=["Target"]) == 1.0

    def test_relevance_never_exceeds_one(self):
        goal = gm.build_goal_from_task("alpha", entities=["E"], directory="/d")
        r = gm.goal_relevance(goal, "alpha here", entities=["E"], directory="/d/x")
        assert r == 1.0


# ── Write / recall re-weight nudges ──────────────────────────────────────────
class TestReweightNudges:
    def test_no_active_goal_is_identity_write(self):
        assert gm.goal_write_gain(gm.EMPTY_GOAL, "anything") == 1.0

    def test_no_active_goal_is_identity_recall(self):
        assert gm.goal_recall_multiplier(gm.EMPTY_GOAL, "anything") == 1.0

    def test_off_task_input_is_identity(self):
        goal = gm.build_goal_from_task("recall pipeline")
        assert gm.goal_write_gain(goal, "unrelated") == 1.0
        assert gm.goal_recall_multiplier(goal, "unrelated") == 1.0

    def test_goal_relevant_write_gets_bounded_boost(self):
        goal = gm.build_goal_from_task("recall pipeline")
        gain = gm.goal_write_gain(goal, "the recall pipeline again")
        assert gain == 1.0 + gm.GOAL_WRITE_WEIGHT  # full relevance
        assert 1.0 < gain <= 1.0 + gm.GOAL_WRITE_WEIGHT

    def test_goal_relevant_recall_gets_bounded_boost(self):
        goal = gm.build_goal_from_task("recall pipeline")
        mult = gm.goal_recall_multiplier(goal, "recall pipeline internals")
        assert mult == 1.0 + gm.GOAL_RECALL_WEIGHT
        assert 1.0 < mult <= 1.0 + gm.GOAL_RECALL_WEIGHT

    def test_partial_relevance_scales_nudge(self):
        goal = gm.build_goal_from_task("recall pipeline latency")  # 3 kw
        # 1 of 3 keywords present → relevance 1/3
        gain = gm.goal_write_gain(goal, "recall only")
        assert abs(gain - (1.0 + gm.GOAL_WRITE_WEIGHT * (1.0 / 3.0))) < 1e-9

    def test_custom_weight_respected(self):
        goal = gm.build_goal_from_task("focus")
        assert gm.goal_write_gain(goal, "focus", weight=0.5) == 1.5


# ── GoalVector introspection ─────────────────────────────────────────────────
class TestGoalVectorDict:
    def test_as_dict_shape(self):
        goal = gm.build_goal_from_task("a task word", entities=["E"], directory="/d")
        d = gm.goal_vector_as_dict(goal)
        assert set(d) == {"label", "keywords", "entities", "directories", "is_active"}
        assert d["is_active"] is True
        assert d["keywords"] == sorted(d["keywords"])  # sorted for determinism

    def test_empty_goal_dict_inactive(self):
        d = gm.goal_vector_as_dict(gm.EMPTY_GOAL)
        assert d["is_active"] is False
        assert d["keywords"] == []
