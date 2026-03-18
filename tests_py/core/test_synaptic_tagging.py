"""Tests for mcp_server.core.synaptic_tagging — Frey & Morris 1997."""

import pytest

from mcp_server.core.synaptic_tagging import (
    find_tagging_candidates,
    compute_tag_boosts,
    apply_synaptic_tags,
)


def _make_memory(id, importance=0.3, heat=0.2, entities=None, age_hours=1.0):
    return {
        "id": id,
        "importance": importance,
        "heat": heat,
        "entities": set(entities or []),
        "age_hours": age_hours,
    }


class TestFindTaggingCandidates:
    def test_strong_memory_triggers_tagging(self):
        existing = [_make_memory(1, importance=0.3, entities=["sqlite", "python"])]
        result = find_tagging_candidates(
            new_memory_entities={"sqlite", "fastmcp"},
            new_memory_importance=0.8,
            existing_memories=existing,
        )
        assert len(result) == 1
        assert result[0]["memory_id"] == 1
        assert "sqlite" in result[0]["matched_entities"]

    def test_weak_new_memory_does_not_trigger(self):
        existing = [_make_memory(1, importance=0.3, entities=["sqlite"])]
        result = find_tagging_candidates(
            new_memory_entities={"sqlite"},
            new_memory_importance=0.4,  # Below trigger threshold
            existing_memories=existing,
        )
        assert result == []

    def test_strong_existing_memory_not_eligible(self):
        existing = [_make_memory(1, importance=0.8, entities=["sqlite"])]
        result = find_tagging_candidates(
            new_memory_entities={"sqlite"},
            new_memory_importance=0.9,
            existing_memories=existing,
        )
        assert result == []

    def test_no_entity_overlap(self):
        existing = [_make_memory(1, entities=["rust", "wasm"])]
        result = find_tagging_candidates(
            new_memory_entities={"python", "sqlite"},
            new_memory_importance=0.8,
            existing_memories=existing,
        )
        assert result == []

    def test_below_min_overlap(self):
        existing = [_make_memory(1, entities=["a", "b", "c", "d", "e"])]
        result = find_tagging_candidates(
            new_memory_entities={"a"},  # 1/5 = 0.2 overlap, but Szymkiewicz = 1/1 = 1.0
            new_memory_importance=0.8,
            existing_memories=existing,
            min_overlap=0.3,
        )
        # Szymkiewicz-Simpson: |{a}| / min(1, 5) = 1.0 >= 0.3
        assert len(result) == 1

    def test_outside_tag_window(self):
        existing = [_make_memory(1, entities=["sqlite"], age_hours=100)]
        result = find_tagging_candidates(
            new_memory_entities={"sqlite"},
            new_memory_importance=0.8,
            existing_memories=existing,
            tag_window_hours=48,
        )
        assert result == []

    def test_max_promotions_cap(self):
        existing = [
            _make_memory(i, entities=["shared"], age_hours=1.0) for i in range(10)
        ]
        result = find_tagging_candidates(
            new_memory_entities={"shared"},
            new_memory_importance=0.9,
            existing_memories=existing,
            max_promotions=3,
        )
        assert len(result) == 3

    def test_ranked_by_overlap(self):
        existing = [
            _make_memory(1, entities=["a", "b"]),
            _make_memory(2, entities=["a", "b", "c"]),
        ]
        result = find_tagging_candidates(
            new_memory_entities={"a", "b", "c"},
            new_memory_importance=0.8,
            existing_memories=existing,
        )
        assert len(result) == 2
        # Memory 2 has 3/3 overlap, memory 1 has 2/2 overlap — both 1.0
        assert result[0]["overlap"] >= result[1]["overlap"]

    def test_empty_entities(self):
        existing = [_make_memory(1, entities=["sqlite"])]
        result = find_tagging_candidates(
            new_memory_entities=set(),
            new_memory_importance=0.9,
            existing_memories=existing,
        )
        assert result == []

    def test_empty_existing(self):
        result = find_tagging_candidates(
            new_memory_entities={"sqlite"},
            new_memory_importance=0.9,
            existing_memories=[],
        )
        assert result == []


class TestComputeTagBoosts:
    def test_full_overlap_gives_full_boost(self):
        result = compute_tag_boosts(
            overlap=1.0,
            current_importance=0.3,
            current_heat=0.2,
            importance_boost=0.25,
            heat_boost=1.5,
        )
        assert result["new_importance"] == pytest.approx(0.55, abs=0.01)
        assert result["new_heat"] == pytest.approx(0.3, abs=0.01)

    def test_partial_overlap_scales_boost(self):
        result = compute_tag_boosts(
            overlap=0.5,
            current_importance=0.3,
            current_heat=0.2,
            importance_boost=0.25,
            heat_boost=1.5,
        )
        assert result["new_importance"] < 0.55  # Less than full overlap
        assert result["new_importance"] > 0.3  # But still boosted

    def test_importance_capped_at_one(self):
        result = compute_tag_boosts(
            overlap=1.0,
            current_importance=0.9,
            current_heat=0.5,
            importance_boost=0.5,
        )
        assert result["new_importance"] <= 1.0

    def test_heat_capped_at_one(self):
        result = compute_tag_boosts(
            overlap=1.0,
            current_importance=0.3,
            current_heat=0.8,
            heat_boost=2.0,
        )
        assert result["new_heat"] <= 1.0

    def test_deltas_are_correct(self):
        result = compute_tag_boosts(
            overlap=1.0,
            current_importance=0.3,
            current_heat=0.2,
        )
        assert result["importance_delta"] == pytest.approx(
            result["new_importance"] - 0.3, abs=0.001
        )
        assert result["heat_delta"] == pytest.approx(
            result["new_heat"] - 0.2, abs=0.001
        )


class TestApplySynapticTags:
    def test_full_pipeline(self):
        existing = [
            _make_memory(1, importance=0.3, heat=0.2, entities=["sqlite", "python"]),
            _make_memory(
                2, importance=0.8, heat=0.9, entities=["sqlite"]
            ),  # too strong
        ]
        result = apply_synaptic_tags(
            new_memory_entities={"sqlite", "fastmcp"},
            new_memory_importance=0.85,
            existing_memories=existing,
        )
        assert len(result) == 1
        assert result[0]["memory_id"] == 1
        assert result[0]["new_importance"] > 0.3
        assert result[0]["new_heat"] > 0.2
        assert "sqlite" in result[0]["matched_entities"]

    def test_no_candidates_returns_empty(self):
        result = apply_synaptic_tags(
            new_memory_entities={"rust"},
            new_memory_importance=0.9,
            existing_memories=[_make_memory(1, entities=["python"])],
        )
        assert result == []

    def test_below_trigger_returns_empty(self):
        result = apply_synaptic_tags(
            new_memory_entities={"sqlite"},
            new_memory_importance=0.3,
            existing_memories=[_make_memory(1, entities=["sqlite"])],
        )
        assert result == []
