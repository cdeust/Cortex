"""Tests for mcp_server.core.session_critique — structured session self-critique."""

from mcp_server.core.session_critique import (
    analyze_tool_usage,
    analyze_decisions,
    analyze_coverage,
    generate_critique,
)


# ── analyze_tool_usage ───────────────────────────────────────────────────


class TestAnalyzeToolUsage:
    def test_empty_tools(self):
        result = analyze_tool_usage([])
        assert result["diversity_score"] == 0.0
        assert len(result["under_used"]) > 0
        assert "No tools were used" in result["suggestions"][0]

    def test_single_tool(self):
        result = analyze_tool_usage(["Read"])
        assert result["diversity_score"] > 0
        assert "Read" not in result["under_used"]

    def test_diverse_tools(self):
        tools = ["Read", "Edit", "Write", "Grep", "Glob", "Bash"]
        result = analyze_tool_usage(tools)
        assert result["diversity_score"] > 0.5

    def test_over_reliance_detected(self):
        tools = ["Read"] * 10 + ["Edit"]
        result = analyze_tool_usage(tools)
        assert "Read" in result["over_reliance"]

    def test_no_over_reliance_with_few_calls(self):
        tools = ["Read", "Read", "Read"]  # Only 3, below threshold of 5
        result = analyze_tool_usage(tools)
        assert result["over_reliance"] == []

    def test_under_used_tools(self):
        result = analyze_tool_usage(["Read", "Edit"])
        assert "Bash" in result["under_used"]
        assert "Grep" in result["under_used"]

    def test_tool_counts(self):
        tools = ["Read", "Read", "Edit", "Bash"]
        result = analyze_tool_usage(tools)
        assert result["tool_counts"]["Read"] == 2
        assert result["tool_counts"]["Edit"] == 1

    def test_low_diversity_suggestion(self):
        result = analyze_tool_usage(["Read"])
        # With only 1 unique tool out of ~9 expected, diversity < 0.3
        if result["diversity_score"] < 0.3:
            assert any("diversity" in s.lower() for s in result["suggestions"])

    def test_many_under_used_suggestion(self):
        result = analyze_tool_usage(["Read"])
        assert any("Unused tools" in s for s in result["suggestions"])


# ── analyze_decisions ────────────────────────────────────────────────────


class TestAnalyzeDecisions:
    def test_empty_memories(self):
        result = analyze_decisions([])
        assert result["decision_count"] == 0
        assert result["reversal_count"] == 0

    def test_detects_decisions_by_tag(self):
        memories = [{"content": "something", "tags": ["decision"]}]
        result = analyze_decisions(memories)
        assert result["decision_count"] == 1

    def test_detects_decisions_by_keyword(self):
        memories = [{"content": "I decided to use Python", "tags": []}]
        result = analyze_decisions(memories)
        assert result["decision_count"] == 1

    def test_detects_reversals(self):
        memories = [
            {"content": "I decided to use Python", "tags": ["decision"]},
            {"content": "Actually, let me switch to Go instead", "tags": []},
        ]
        result = analyze_decisions(memories)
        assert result["reversal_count"] >= 1

    def test_multiple_reversals_trigger_suggestion(self):
        memories = [
            {"content": "actually changed approach", "tags": []},
            {"content": "wait, let me redo this", "tags": []},
            {"content": "on second thought, revert", "tags": []},
        ]
        result = analyze_decisions(memories)
        assert any("reversal" in s.lower() for s in result["suggestions"])

    def test_confidence_average(self):
        memories = [
            {"content": "decided X", "tags": ["decision"], "confidence": 0.8},
            {"content": "chose Y", "tags": ["decision"], "confidence": 0.6},
        ]
        result = analyze_decisions(memories)
        assert result["confidence_avg"] == 0.7

    def test_low_confidence_suggestion(self):
        memories = [
            {"content": "decided X", "tags": ["decision"], "confidence": 0.2},
            {"content": "chose Y", "tags": ["decision"], "confidence": 0.3},
        ]
        result = analyze_decisions(memories)
        assert any("confidence" in s.lower() for s in result["suggestions"])

    def test_no_decisions_with_many_memories_suggestion(self):
        memories = [{"content": f"memory {i}", "tags": []} for i in range(10)]
        result = analyze_decisions(memories)
        assert any("No explicit decisions" in s for s in result["suggestions"])

    def test_session_memories_used_for_reversals(self):
        base = [{"content": "decided X", "tags": ["decision"]}]
        session = [{"content": "scratch that, try again", "tags": []}]
        result = analyze_decisions(base, session_memories=session)
        assert result["reversal_count"] >= 1


# ── analyze_coverage ─────────────────────────────────────────────────────


class TestAnalyzeCoverage:
    def test_empty_inputs(self):
        result = analyze_coverage([], [])
        assert result["file_coverage"] == 0.0
        assert result["breadth_score"] == 0.0
        assert result["depth_score"] == 0.0

    def test_file_coverage(self):
        result = analyze_coverage(
            ["src/a.py", "src/b.py"],
            [],
            total_domain_files=10,
        )
        assert result["file_coverage"] == 0.2

    def test_entity_coverage(self):
        result = analyze_coverage(
            [],
            ["User", "Product"],
            total_entities=10,
        )
        assert result["entity_coverage"] == 0.2

    def test_breadth_score(self):
        files = ["src/a.py", "lib/b.py", "tests/c.py", "docs/d.py", "config/e.py"]
        result = analyze_coverage(files, [])
        assert result["breadth_score"] == 1.0  # 5 unique dirs / 5 = 1.0

    def test_depth_score(self):
        files = ["src/a.py"] * 5
        result = analyze_coverage(files, [])
        assert result["depth_score"] == 1.0  # max_visits=5 / 5 = 1.0

    def test_narrow_focus_suggestion(self):
        files = ["src/a.py", "src/b.py", "src/c.py", "src/d.py"]
        result = analyze_coverage(files, [])
        if result["breadth_score"] < 0.2:
            assert any("Narrow focus" in s for s in result["suggestions"])

    def test_deep_narrow_suggestion(self):
        files = ["src/a.py"] * 10
        result = analyze_coverage(files, [])
        if result["depth_score"] > 0.8 and result["breadth_score"] < 0.3:
            assert any("Deep but narrow" in s for s in result["suggestions"])

    def test_low_entity_coverage_suggestion(self):
        result = analyze_coverage([], [], total_entities=20)
        assert any("entity coverage" in s.lower() for s in result["suggestions"])

    def test_coverage_capped_at_one(self):
        result = analyze_coverage(
            ["a.py"] * 20,
            ["X"] * 20,
            total_domain_files=5,
            total_entities=3,
        )
        assert result["file_coverage"] <= 1.0
        assert result["entity_coverage"] <= 1.0


# ── generate_critique ────────────────────────────────────────────────────


class TestGenerateCritique:
    def test_empty_session(self):
        result = generate_critique([], [])
        assert "overall_score" in result
        assert "critique_text" in result
        assert "top_suggestions" in result

    def test_overall_score_range(self):
        result = generate_critique(
            ["Read", "Edit", "Bash", "Grep"],
            [{"content": "decided X", "tags": ["decision"], "confidence": 0.9}],
            files_touched=["a/x.py", "b/y.py"],
        )
        assert 0 <= result["overall_score"] <= 1.0

    def test_includes_all_analyses(self):
        result = generate_critique(["Read"], [])
        assert "tool_analysis" in result
        assert "decision_analysis" in result
        assert "coverage_analysis" in result

    def test_critique_text_markdown(self):
        result = generate_critique(["Read"], [])
        assert "## Session Self-Critique" in result["critique_text"]

    def test_duration_in_text(self):
        result = generate_critique(
            ["Read"],
            [],
            duration_minutes=30,
            turn_count=15,
        )
        assert "30 min" in result["critique_text"]
        assert "15 turns" in result["critique_text"]

    def test_top_suggestions_limited(self):
        result = generate_critique(["Read"], [])
        assert len(result["top_suggestions"]) <= 5

    def test_no_issues_text(self):
        tools = ["Read", "Edit", "Write", "Grep", "Glob", "Bash", "Agent"]
        memories = [{"content": "decided X", "tags": ["decision"], "confidence": 0.9}]
        result = generate_critique(
            tools,
            memories,
            files_touched=["a/x.py", "b/y.py", "c/z.py", "d/w.py", "e/v.py"],
        )
        if not result["top_suggestions"]:
            assert "No significant issues" in result["critique_text"]
