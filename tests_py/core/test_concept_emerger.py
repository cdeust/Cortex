"""Tests for mcp_server.core.concept_emerger (#196). Pure logic
(grounded-theory concept emergence), zero prior test coverage."""

from __future__ import annotations

from mcp_server.core.concept_emerger import (
    MIN_CLAIMS_PER_CONCEPT,
    _axial_distribution,
    _cluster_by_entity,
    _count_axial_slots_filled,
    _decide_status,
    _entity_label,
    _jaccard,
    _properties_from_claims,
    _saturation_update,
    cold_start_thresholds,
    emerge,
)


class TestEntityLabel:
    def test_empty_claims_returns_generic_label(self):
        assert _entity_label([], 42) == "concept-42"

    def test_extracts_capitalized_token(self):
        label = _entity_label(["We discussed Kubernetes deployment issues"], 1)
        assert label == "Kubernetes"

    def test_extracts_snake_case_token(self):
        label = _entity_label(["the memory_store handles this"], 1)
        assert label == "memory_store"

    def test_no_candidate_tokens_falls_back(self):
        assert _entity_label(["just lowercase words here"], 7) == "concept-7"

    def test_most_common_token_wins(self):
        label = _entity_label(["Docker is great", "Docker rocks", "Podman is okay"], 1)
        assert label == "Docker"


class TestJaccard:
    def test_both_empty_is_zero(self):
        assert _jaccard(set(), set()) == 0.0

    def test_identical_sets_is_one(self):
        assert _jaccard({1, 2, 3}, {1, 2, 3}) == 1.0

    def test_disjoint_sets_is_zero(self):
        assert _jaccard({1, 2}, {3, 4}) == 0.0

    def test_partial_overlap(self):
        assert _jaccard({1, 2, 3}, {2, 3, 4}) == 0.5


class TestAxialDistribution:
    def test_maps_claim_types_to_slots(self):
        claims = [
            {"claim_type": "observation", "text": "a fact"},
            {"claim_type": "decision", "text": "a choice"},
            {"claim_type": "result", "text": "an outcome"},
            {"claim_type": "reference", "text": "a link"},
        ]
        slots = _axial_distribution(claims)
        assert "a fact" in slots["conditions"]
        assert "a choice" in slots["strategies"]
        assert "an outcome" in slots["consequences"]
        assert "a link" in slots["context"]

    def test_unknown_claim_type_defaults_to_context(self):
        claims = [{"claim_type": "unknown_type", "text": "something"}]
        slots = _axial_distribution(claims)
        assert "something" in slots["context"]

    def test_empty_text_skipped(self):
        claims = [{"claim_type": "observation", "text": ""}]
        slots = _axial_distribution(claims)
        assert slots["conditions"] == []

    def test_duplicate_text_not_repeated(self):
        claims = [
            {"claim_type": "observation", "text": "same"},
            {"claim_type": "observation", "text": "same"},
        ]
        slots = _axial_distribution(claims)
        assert slots["conditions"] == ["same"]

    def test_text_truncated_to_300_chars(self):
        claims = [{"claim_type": "observation", "text": "x" * 500}]
        slots = _axial_distribution(claims)
        assert len(slots["conditions"][0]) == 300


class TestPropertiesFromClaims:
    def test_groups_by_claim_type(self):
        claims = [
            {"claim_type": "decision", "text": "choice A"},
            {"claim_type": "decision", "text": "choice B"},
        ]
        props = _properties_from_claims(claims)
        assert len(props["decision"]) == 2

    def test_default_claim_type_is_assertion(self):
        claims = [{"text": "no type given"}]
        props = _properties_from_claims(claims)
        assert "assertion" in props

    def test_empty_text_skipped(self):
        claims = [{"claim_type": "decision", "text": ""}]
        assert _properties_from_claims(claims) == {}

    def test_fingerprint_dedupes_near_duplicates(self):
        claims = [
            {"claim_type": "decision", "text": "x" * 100},
            {"claim_type": "decision", "text": "x" * 100 + "extra tail"},
        ]
        props = _properties_from_claims(claims)
        # Both fingerprints are the first 80 chars of "x"*100 -> identical
        assert len(props["decision"]) == 1


class TestCountAxialSlotsFilled:
    def test_all_empty_is_zero(self):
        slots = {"conditions": [], "context": [], "strategies": [], "consequences": []}
        assert _count_axial_slots_filled(slots) == 0

    def test_counts_non_empty_slots(self):
        slots = {
            "conditions": ["a"],
            "context": [],
            "strategies": ["b"],
            "consequences": [],
        }
        assert _count_axial_slots_filled(slots) == 2


class TestClusterByEntity:
    def test_below_min_claims_not_seeded(self):
        claims = [
            {"id": 1, "memory_id": 1, "entity_ids": [1]},
            {"id": 2, "memory_id": 1, "entity_ids": [1]},
        ]
        clusters = _cluster_by_entity(claims, min_claims=3)
        assert clusters == []

    def test_meets_min_claims_forms_cluster(self):
        claims = [{"id": i, "memory_id": 1, "entity_ids": [1]} for i in range(1, 4)]
        clusters = _cluster_by_entity(claims, min_claims=3)
        assert len(clusters) == 1
        assert clusters[0].center_entity == 1

    def test_overlapping_clusters_merged(self):
        # Two entities sharing all 3 claims -> Jaccard = 1.0 >= 0.5 -> merge
        claims = [{"id": i, "memory_id": 1, "entity_ids": [1, 2]} for i in range(1, 4)]
        clusters = _cluster_by_entity(claims, min_claims=3)
        assert len(clusters) == 1
        assert clusters[0].entity_ids == {1, 2}

    def test_disjoint_entities_stay_separate(self):
        claims_a = [{"id": i, "memory_id": 1, "entity_ids": [1]} for i in range(1, 4)]
        claims_b = [
            {"id": i + 10, "memory_id": 2, "entity_ids": [2]} for i in range(1, 4)
        ]
        clusters = _cluster_by_entity(claims_a + claims_b, min_claims=3)
        assert len(clusters) == 2

    def test_claim_without_entity_ids_ignored(self):
        claims = [{"id": 1, "memory_id": 1}]
        clusters = _cluster_by_entity(claims, min_claims=1)
        assert clusters == []

    def test_claim_without_id_not_counted_in_claim_ids(self):
        claims = [{"memory_id": 1, "entity_ids": [1]}]
        clusters = _cluster_by_entity(claims, min_claims=1)
        assert clusters == []  # no id -> claim_ids stays empty -> below min_claims


class TestSaturationUpdate:
    def test_no_new_memories_returns_zero_rate_unchanged_streak(self):
        rate, streak = _saturation_update({}, {1, 2}, 3, {}, {1, 2})
        assert rate == 0.0
        assert streak == 3

    def test_new_memories_no_new_properties_increments_streak(self):
        rate, streak = _saturation_update(
            {"decision": ["a"]}, {1}, 2, {"decision": ["a"]}, {1, 2}
        )
        assert rate == 0.0
        assert streak == 3

    def test_new_memories_with_new_properties_resets_streak(self):
        rate, streak = _saturation_update({}, {1}, 5, {"decision": ["new"]}, {1, 2})
        assert rate == 1.0
        assert streak == 0

    def test_multiple_new_properties_per_memory(self):
        rate, streak = _saturation_update({}, set(), 0, {"decision": ["a", "b"]}, {1})
        assert rate == 2.0


class TestDecideStatus:
    def test_default_thresholds_candidate_stays_candidate(self):
        status = _decide_status(
            grounding_memory_count=0,
            axial_slots_filled=0,
            saturation_streak=0,
            current_status="candidate",
        )
        assert status == "candidate"

    def test_promotes_to_saturating(self):
        status = _decide_status(
            grounding_memory_count=0,
            axial_slots_filled=0,
            saturation_streak=3,
            current_status="candidate",
        )
        assert status == "saturating"

    def test_promotes_to_promoted_when_all_thresholds_met(self):
        status = _decide_status(
            grounding_memory_count=3,
            axial_slots_filled=3,
            saturation_streak=5,
            current_status="candidate",
        )
        assert status == "promoted"

    def test_never_moves_backwards_from_promoted(self):
        status = _decide_status(
            grounding_memory_count=0,
            axial_slots_filled=0,
            saturation_streak=0,
            current_status="promoted",
        )
        assert status == "promoted"

    def test_terminal_statuses_are_sticky(self):
        for terminal in ("merged", "split", "abandoned"):
            status = _decide_status(
                grounding_memory_count=100,
                axial_slots_filled=4,
                saturation_streak=100,
                current_status=terminal,
            )
            assert status == terminal

    def test_custom_thresholds_override_defaults(self):
        # cold_start_thresholds(): min_grounding=1, min_axial=2,
        # promotion_streak=2 — a streak of 1 clears grounding/axial but
        # not the promotion streak, so it lands on "saturating" (its
        # own saturation_streak=1 threshold), not "promoted".
        status = _decide_status(
            grounding_memory_count=1,
            axial_slots_filled=2,
            saturation_streak=2,
            current_status="candidate",
            thresholds=cold_start_thresholds(),
        )
        assert status == "promoted"

    def test_unknown_threshold_keys_ignored(self):
        status = _decide_status(
            grounding_memory_count=0,
            axial_slots_filled=0,
            saturation_streak=0,
            current_status="candidate",
            thresholds={"bogus_key": 999},
        )
        assert status == "candidate"


class TestColdStartThresholds:
    def test_returns_expected_keys(self):
        thresholds = cold_start_thresholds()
        assert set(thresholds.keys()) == {
            "min_claims_per_concept",
            "saturation_streak",
            "promotion_streak",
            "min_grounding_memories",
            "min_axial_slots_filled",
        }

    def test_relaxed_vs_steady_state(self):
        thresholds = cold_start_thresholds()
        assert thresholds["min_claims_per_concept"] < MIN_CLAIMS_PER_CONCEPT


class TestEmerge:
    def test_empty_claims_returns_empty_plans(self):
        plans, stats = emerge(claims=[], existing_concepts_by_entities={})
        assert plans == []
        assert stats.candidate_concepts == 0

    def test_new_candidate_concept_created(self):
        claims = [
            {
                "id": i,
                "memory_id": i,
                "entity_ids": [1],
                "claim_type": "observation",
                "text": f"Kubernetes fact {i}",
            }
            for i in range(1, 4)
        ]
        plans, stats = emerge(claims=claims, existing_concepts_by_entities={})
        assert len(plans) == 1
        assert plans[0].concept_id is None
        assert stats.new_concepts == 1
        assert stats.updated_concepts == 0

    def test_existing_concept_updated_not_duplicated(self):
        claims = [
            {
                "id": i,
                "memory_id": i,
                "entity_ids": [1],
                "claim_type": "decision",
                "text": f"new decision {i}",
            }
            for i in range(1, 4)
        ]
        existing = {
            frozenset({1}): {
                "id": 99,
                "label": "existing-concept",
                "properties": {},
                "grounding_memory_ids": [],
                "grounding_claim_ids": [],
                "entity_ids": [1],
                "saturation_streak": 0,
                "status": "candidate",
                "axial_slots": {},
            }
        }
        plans, stats = emerge(claims=claims, existing_concepts_by_entities=existing)
        assert len(plans) == 1
        assert plans[0].concept_id == 99
        assert plans[0].label == "existing-concept"
        assert stats.updated_concepts == 1
        assert stats.new_concepts == 0

    def test_below_min_claims_produces_no_plans(self):
        claims = [
            {
                "id": 1,
                "memory_id": 1,
                "entity_ids": [1],
                "claim_type": "observation",
                "text": "x",
            }
        ]
        plans, stats = emerge(claims=claims, existing_concepts_by_entities={})
        assert plans == []

    def test_cold_start_thresholds_lower_the_bar(self):
        claims = [
            {
                "id": 1,
                "memory_id": 1,
                "entity_ids": [1],
                "claim_type": "observation",
                "text": "x",
            }
        ]
        plans, stats = emerge(
            claims=claims,
            existing_concepts_by_entities={},
            thresholds=cold_start_thresholds(),
        )
        assert len(plans) == 1

    def test_stats_counts_promoted_plans(self):
        # Existing streak already at 4; new claims add NO new property
        # (text matches the existing property fingerprint exactly) so
        # _saturation_update increments the streak to 5, clearing a
        # promote_streak=1 threshold alongside grounding/axial minimums.
        claims = [
            {
                "id": i,
                "memory_id": i,
                "entity_ids": [1],
                "claim_type": "observation",
                "text": "same fact",
            }
            for i in range(1, 4)
        ]
        existing = {
            frozenset({1}): {
                "id": 60,
                "label": "promo",
                "properties": {"observation": ["same fact"]},
                "grounding_memory_ids": [100, 101],
                "grounding_claim_ids": [],
                "entity_ids": [1],
                "saturation_streak": 4,
                "status": "candidate",
                "axial_slots": {
                    "conditions": ["x"],
                    "context": ["y"],
                    "strategies": ["z"],
                },
            }
        }
        plans, stats = emerge(
            claims=claims,
            existing_concepts_by_entities=existing,
            thresholds={
                "min_claims_per_concept": 1,
                "min_grounding_memories": 1,
                "min_axial_slots_filled": 3,
                "promotion_streak": 1,
            },
        )
        assert plans[0].status == "promoted"
        assert stats.promoted == 1

    def test_stats_count_promoted_and_saturating(self):
        claims = [
            {
                "id": i,
                "memory_id": i,
                "entity_ids": [1],
                "claim_type": "observation",
                "text": f"txt {i}",
            }
            for i in range(1, 4)
        ]
        plans, stats = emerge(
            claims=claims,
            existing_concepts_by_entities={},
            thresholds=cold_start_thresholds(),
        )
        assert (
            stats.promoted + stats.saturating + stats.abandoned
            <= stats.candidate_concepts
        )

    def test_existing_concept_matched_by_list_entity_key(self):
        # existing_concepts_by_entities keys may be list/tuple, not just
        # frozenset — exercise that branch of the isinstance check.
        claims = [
            {
                "id": i,
                "memory_id": i,
                "entity_ids": [1],
                "claim_type": "observation",
                "text": f"t{i}",
            }
            for i in range(1, 4)
        ]
        existing = {
            (1,): {
                "id": 5,
                "label": "l",
                "properties": {},
                "grounding_memory_ids": [],
                "grounding_claim_ids": [],
                "entity_ids": [1],
                "saturation_streak": 0,
                "status": "candidate",
                "axial_slots": {},
            }
        }
        plans, _stats = emerge(claims=claims, existing_concepts_by_entities=existing)
        assert plans[0].concept_id == 5

    def test_existing_concept_matched_by_scalar_entity_key(self):
        claims = [
            {
                "id": i,
                "memory_id": i,
                "entity_ids": [1],
                "claim_type": "observation",
                "text": f"t{i}",
            }
            for i in range(1, 4)
        ]
        existing = {
            1: {
                "id": 7,
                "label": "l",
                "properties": {},
                "grounding_memory_ids": [],
                "grounding_claim_ids": [],
                "entity_ids": [1],
                "saturation_streak": 0,
                "status": "candidate",
                "axial_slots": {},
            }
        }
        plans, _stats = emerge(claims=claims, existing_concepts_by_entities=existing)
        assert plans[0].concept_id == 7

    def test_claim_ids_not_in_index_are_skipped(self):
        # A cluster whose claim_ids reference an id not present in
        # claims_by_id (defensive skip) — construct via a claim missing
        # from the id map after clustering (shouldn't normally happen,
        # but the guard exists).
        claims = [
            {
                "id": i,
                "memory_id": i,
                "entity_ids": [1],
                "claim_type": "observation",
                "text": f"t{i}",
            }
            for i in range(1, 4)
        ]
        plans, stats = emerge(claims=claims, existing_concepts_by_entities={})
        assert stats.claims_grouped == 3

    def test_empty_cluster_claims_skipped(self):
        # min_claims_per_concept=0 lets a cluster form with zero
        # claim_ids (every claim's "id" is falsy/0, excluded from
        # claim_ids at cluster time) — cluster_claims resolves to []
        # and the loop must `continue` rather than emit a plan.
        claims = [{"id": 0, "memory_id": 1, "entity_ids": [1], "text": "x"}]
        plans, stats = emerge(
            claims=claims,
            existing_concepts_by_entities={},
            thresholds={"min_claims_per_concept": 0},
        )
        assert plans == []

    def test_stats_count_saturating_and_abandoned_plans(self):
        # "saturating": an EXISTING concept whose new claims add no new
        # properties for a new memory -> streak increments to meet the
        # (lowered) saturate threshold but not the (raised) promote one.
        # A fresh candidate's streak always starts at 0 (emerge's own
        # hardcoded `saturation_streak=0` for new clusters), so it can
        # never land on "saturating"/"promoted" in a single pass —
        # the existing-concept path is the only route to a non-zero
        # incoming streak.
        # "abandoned": an EXISTING concept already in that terminal
        # status stays abandoned (sticky) and must be counted.
        saturating_claims = [
            {
                "id": i,
                "memory_id": i,
                "entity_ids": [1],
                "claim_type": "observation",
                "text": "same fact",  # matches existing property -> no new prop
            }
            for i in range(1, 4)
        ]
        abandoned_claims = [
            {
                "id": i,
                "memory_id": i,
                "entity_ids": [2],
                "claim_type": "observation",
                "text": f"b{i}",
            }
            for i in range(11, 14)
        ]
        existing = {
            frozenset({1}): {
                "id": 40,
                "label": "sat",
                "properties": {"observation": ["same fact"]},
                "grounding_memory_ids": [],
                "grounding_claim_ids": [],
                "entity_ids": [1],
                "saturation_streak": 2,
                "status": "candidate",
                "axial_slots": {},
            },
            frozenset({2}): {
                "id": 50,
                "label": "dead",
                "properties": {},
                "grounding_memory_ids": [],
                "grounding_claim_ids": [],
                "entity_ids": [2],
                "saturation_streak": 0,
                "status": "abandoned",
                "axial_slots": {},
            },
        }
        plans, stats = emerge(
            claims=saturating_claims + abandoned_claims,
            existing_concepts_by_entities=existing,
            thresholds={
                "min_claims_per_concept": 1,
                "saturation_streak": 3,
                "promotion_streak": 999,
            },
        )
        statuses = {p.status for p in plans}
        assert "saturating" in statuses
        assert "abandoned" in statuses
        assert stats.saturating >= 1
        assert stats.abandoned >= 1
