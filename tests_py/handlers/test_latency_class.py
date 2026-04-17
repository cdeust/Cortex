"""Phase 5 step 3: latency-class registry tests.

Asserts:
    - classify() returns a valid class for all registered tools
    - heuristic fallback classifies unknown tools sensibly
    - interactive/batch are the only valid classes
    - DEFAULT_SEMAPHORE covers every class

Source: docs/program/phase-5-pool-admission-design.md §1.1.
"""

from __future__ import annotations

import pytest

from mcp_server.handlers.latency_class import (
    DEFAULT_SEMAPHORE,
    all_registered_tools,
    classify,
)


class TestRegistry:
    def test_every_registered_tool_classifies_to_valid_class(self):
        for tool in all_registered_tools():
            cls = classify(tool)
            assert cls in ("interactive", "batch"), (
                f"{tool}: unexpected class {cls!r}"
            )

    def test_default_semaphore_covers_both_classes(self):
        assert "interactive" in DEFAULT_SEMAPHORE
        assert "batch" in DEFAULT_SEMAPHORE
        assert DEFAULT_SEMAPHORE["interactive"] > DEFAULT_SEMAPHORE["batch"]

    def test_interactive_semaphore_is_higher(self):
        """Interactive tools should have higher concurrency budget than
        batch tools (more of them can run in parallel)."""
        assert DEFAULT_SEMAPHORE["interactive"] >= 2
        assert DEFAULT_SEMAPHORE["batch"] >= 1


class TestCoreClassification:
    @pytest.mark.parametrize(
        "tool",
        [
            "recall",
            "remember",
            "anchor",
            "detect_domain",
            "memory_stats",
            "query_methodology",
            "drill_down",
        ],
    )
    def test_hot_path_tools_interactive(self, tool):
        assert classify(tool) == "interactive"

    @pytest.mark.parametrize(
        "tool",
        [
            "consolidate",
            "seed_project",
            "codebase_analyze",
            "backfill_memories",
            "ingest_codebase",
            "ingest_prd",
        ],
    )
    def test_long_running_tools_batch(self, tool):
        assert classify(tool) == "batch"


class TestHeuristicFallback:
    """Unknown tool names fall back to name-based classification."""

    @pytest.mark.parametrize(
        "tool,expected",
        [
            ("some_new_ingest_tool", "batch"),
            ("rebuild_something_new", "batch"),
            ("seed_whatever", "batch"),
            ("refresh_index_pipeline", "batch"),
            ("new_recall_variant", "interactive"),
            ("explore_xyz", "interactive"),
            ("get_anything", "interactive"),
        ],
    )
    def test_heuristic_classification(self, tool, expected):
        assert classify(tool) == expected
