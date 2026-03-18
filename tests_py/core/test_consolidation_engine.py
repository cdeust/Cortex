"""Tests for mcp_server.core.consolidation_engine — CLS orchestration."""

from mcp_server.core.consolidation_engine import (
    plan_cls_consolidation,
    find_near_duplicates,
    summarize_action_group,
    should_reclassify,
)


def _exact_sim(a, b):
    """Exact match similarity for testing."""
    if a is None or b is None:
        return 0.0
    return 1.0 if a == b else 0.0


class TestPlanClsConsolidation:
    def test_recurring_pattern_creates_semantic(self):
        # 4 memories with same embedding, from 2 sessions
        mems = [
            {
                "id": i,
                "embedding": b"pattern",
                "content": "always use UTC",
                "source": f"s{i % 2}",
                "tags": ["time"],
            }
            for i in range(4)
        ]
        plan = plan_cls_consolidation(
            episodic_memories=mems,
            existing_semantics=[],
            similarity_fn=_exact_sim,
            cluster_threshold=0.9,
            min_occurrences=3,
            min_sessions=2,
        )
        assert plan["patterns_found"] >= 1
        assert len(plan["new_semantics"]) >= 1
        assert "semantic" in plan["new_semantics"][0]["tags"]
        assert "auto-abstracted" in plan["new_semantics"][0]["tags"]

    def test_no_patterns_in_small_set(self):
        mems = [
            {"id": 1, "embedding": b"a", "content": "x", "source": "s1"},
            {"id": 2, "embedding": b"b", "content": "y", "source": "s2"},
        ]
        plan = plan_cls_consolidation(mems, [], _exact_sim, min_occurrences=3)
        assert plan["patterns_found"] == 0
        assert len(plan["new_semantics"]) == 0

    def test_inconsistent_skipped(self):
        # Pattern with contradictory content
        mems = [
            {
                "id": 1,
                "embedding": b"same",
                "content": "use UTC",
                "source": "s1",
                "tags": [],
            },
            {
                "id": 2,
                "embedding": b"same",
                "content": "don't use UTC anymore",
                "source": "s2",
                "tags": [],
            },
            {
                "id": 3,
                "embedding": b"same",
                "content": "use UTC always",
                "source": "s1",
                "tags": [],
            },
        ]
        plan = plan_cls_consolidation(
            mems,
            [],
            _exact_sim,
            cluster_threshold=0.9,
            min_occurrences=3,
            min_sessions=2,
        )
        assert plan["skipped_inconsistent"] >= 1

    def test_duplicate_skipped(self):
        mems = [
            {
                "id": i,
                "embedding": b"same",
                "content": "always use UTC",
                "source": f"s{i % 2}",
                "tags": [],
            }
            for i in range(4)
        ]
        existing = [{"content": "use UTC", "embedding": b"same"}]
        plan = plan_cls_consolidation(
            mems,
            existing,
            _exact_sim,
            cluster_threshold=0.9,
            dedup_threshold=0.85,
            min_occurrences=3,
            min_sessions=2,
        )
        assert plan["skipped_duplicate"] >= 1

    def test_empty_input(self):
        plan = plan_cls_consolidation([], [], _exact_sim)
        assert plan["patterns_found"] == 0
        assert len(plan["new_semantics"]) == 0


class TestFindNearDuplicates:
    def test_finds_duplicates(self):
        mems = [
            {"id": 1, "embedding": b"same", "heat": 0.9},
            {"id": 2, "embedding": b"same", "heat": 0.3},
            {"id": 3, "embedding": b"diff", "heat": 0.5},
        ]
        dups = find_near_duplicates(mems, _exact_sim, threshold=0.95)
        assert len(dups) == 1
        assert dups[0] == (1, 2)  # Keep higher heat

    def test_no_duplicates(self):
        mems = [
            {"id": 1, "embedding": b"a", "heat": 0.9},
            {"id": 2, "embedding": b"b", "heat": 0.3},
        ]
        dups = find_near_duplicates(mems, _exact_sim, threshold=0.95)
        assert len(dups) == 0

    def test_null_embeddings_skipped(self):
        mems = [
            {"id": 1, "embedding": None, "heat": 0.9},
            {"id": 2, "embedding": b"a", "heat": 0.3},
        ]
        dups = find_near_duplicates(mems, _exact_sim, threshold=0.95)
        assert len(dups) == 0

    def test_keeps_higher_heat(self):
        mems = [
            {"id": 1, "embedding": b"same", "heat": 0.2},
            {"id": 2, "embedding": b"same", "heat": 0.8},
        ]
        dups = find_near_duplicates(mems, _exact_sim, threshold=0.95)
        assert dups[0] == (2, 1)  # Keep id=2 (higher heat)


class TestSummarizeActionGroup:
    def test_summarizes_actions(self):
        actions = [
            {"type": "edit", "file": "foo.py"},
            {"type": "edit", "file": "bar.py"},
            {"type": "run", "file": "test.py"},
        ]
        summary = summarize_action_group(actions)
        assert summary is not None
        assert "edit" in summary
        assert "run" in summary
        assert "foo.py" in summary

    def test_too_few_actions(self):
        actions = [{"type": "edit"}, {"type": "run"}]
        assert summarize_action_group(actions) is None

    def test_caps_file_list(self):
        actions = [{"type": "edit", "file": f"file{i}.py"} for i in range(10)]
        summary = summarize_action_group(actions, min_actions=3)
        assert "+5 more" in summary

    def test_no_files(self):
        actions = [{"type": "think"}] * 3
        summary = summarize_action_group(actions)
        assert summary is not None
        assert "think" in summary


class TestShouldReclassify:
    def test_frequent_access_triggers(self):
        mem = {"store_type": "episodic", "content": "always use UTC", "tags": []}
        assert should_reclassify(mem, access_count=5) is True

    def test_related_semantics_triggers(self):
        mem = {"store_type": "episodic", "content": "follow this pattern", "tags": []}
        assert should_reclassify(mem, related_semantics=3) is True

    def test_already_semantic_no_change(self):
        mem = {"store_type": "semantic", "content": "a rule"}
        assert should_reclassify(mem, access_count=10) is False

    def test_episodic_content_stays(self):
        mem = {"store_type": "episodic", "content": "error at line 42 in foo.py:42"}
        assert should_reclassify(mem, access_count=10) is False

    def test_low_access_stays(self):
        mem = {"store_type": "episodic", "content": "always use UTC"}
        assert should_reclassify(mem, access_count=2) is False
