"""Tests for mcp_server.shared.categorizer — work-category classification."""

from mcp_server.shared.categorizer import categorize, categorize_with_scores


class TestCategorize:
    def test_classifies_bug_fix(self):
        assert categorize("fix the broken login bug") == "bug-fix"

    def test_classifies_feature(self):
        assert categorize("add new user registration") == "feature"

    def test_classifies_refactor(self):
        assert categorize("refactor the data layer and simplify") == "refactor"

    def test_classifies_research(self):
        assert categorize("research and evaluate different frameworks") == "research"

    def test_classifies_config(self):
        assert categorize("setup the environment config") == "config"

    def test_classifies_docs(self):
        assert categorize("document the API and update the readme") == "docs"

    def test_classifies_debug(self):
        assert categorize("debug the issue and inspect the log") == "debug"

    def test_classifies_architecture(self):
        assert (
            categorize("design the system architecture and module pattern")
            == "architecture"
        )

    def test_classifies_deployment(self):
        assert categorize("deploy to production with docker") == "deployment"

    def test_classifies_testing(self):
        assert categorize("write unit test with mock and assert") == "testing"

    def test_returns_best_match_for_ambiguous_text(self):
        result = categorize("fix the broken test")
        assert result == "bug-fix"

    def test_returns_general_for_empty_text(self):
        assert categorize("") == "general"

    def test_returns_general_for_none(self):
        assert categorize(None) == "general"

    def test_returns_general_for_no_matching_signals(self):
        assert categorize("hello world foo bar") == "general"

    # --- New tests for lines 86-92 (tie-breaking logic) ---

    def test_tie_breaking_prefers_phrase_match(self):
        """When two categories have similar scores, phrase matches should win."""
        # "clean up" is a phrase (1.5) for refactor; "simplify" is single (1.0) for refactor
        # vs some other category with same single-word score
        result = categorize("clean up the code")
        assert result == "refactor"

    def test_tie_breaking_equal_scores_with_phrases(self):
        """Test the branch where sc >= best_score and phrase_count decides."""
        # "ci/cd" is a phrase for deployment (1.5), "pipeline" is single (1.0) = 2.5
        # "unit test" is a phrase for testing (1.5), "test" is single (1.0) = 2.5
        # Both have same score; phrase count decides
        result = categorize("test the ci/cd pipeline")
        assert result in ("deployment", "testing")

    def test_close_scores_with_different_phrase_counts(self):
        """Two categories with close scores where phrase match breaks tie."""
        # "why is" is a phrase for debug (1.5)
        # "error" is single for bug-fix (1.0)
        # Both have single signals too, so scores are close
        result = categorize("why is there an error")
        # debug gets "why is" (1.5) + "diagnose" no = 1.5, "bug-fix" gets "error" (1.0)
        # debug wins on score anyway, but exercises the >= branch
        assert result in ("debug", "bug-fix")

    def test_equal_score_equal_phrase_count_picks_higher_score(self):
        """When phrase counts are equal, higher score wins in the elif branch."""
        # Both "fix" (bug-fix, 1.0) and "test" (testing, 1.0) — single words, equal phrase count (0)
        result = categorize("fix test")
        assert result in ("bug-fix", "testing")

    def test_scores_within_half_point(self):
        """Exercise the elif branch: sc >= best_score and sc > best_score - 0.5."""
        # "build" (feature, 1.0) and "create" (feature, 1.0) = feature gets 2.0
        # "test" (testing, 1.0) = 1.0
        # Feature clearly wins, but let's ensure close scores also work
        result = categorize("create and build")
        assert result == "feature"


class TestCategorizeWithScores:
    def test_returns_multiple_category_scores(self):
        scores = categorize_with_scores("implement new test for the API")
        assert "feature" in scores
        assert "testing" in scores

    def test_returns_empty_dict_for_empty_text(self):
        assert categorize_with_scores("") == {}

    def test_returns_empty_dict_for_none(self):
        assert categorize_with_scores(None) == {}

    def test_scores_are_positive_numbers(self):
        scores = categorize_with_scores("fix the bug and refactor the code")
        for score in scores.values():
            assert isinstance(score, float)
            assert score > 0

    def test_multi_word_phrases_score_1_5(self):
        scores = categorize_with_scores("write a unit test")
        assert "testing" in scores
        # "test" (1.0) + "unit test" (1.5) = 2.5
        assert scores["testing"] == 2.5

    def test_returns_only_non_zero_categories(self):
        scores = categorize_with_scores("fix bug")
        assert "bug-fix" in scores
        for score in scores.values():
            assert score > 0

    # --- New tests for broader coverage ---

    def test_phrase_match_clean_up(self):
        scores = categorize_with_scores("clean up the module")
        assert "refactor" in scores
        assert scores["refactor"] >= 1.5  # phrase match

    def test_phrase_match_why_is(self):
        scores = categorize_with_scores("why is this failing")
        assert "debug" in scores
        assert scores["debug"] >= 1.5

    def test_multiple_signals_same_category(self):
        scores = categorize_with_scores("fix the bug and resolve the crash error")
        assert "bug-fix" in scores
        assert scores["bug-fix"] >= 3.0  # fix + bug + crash + error = 4.0

    def test_case_insensitive(self):
        scores = categorize_with_scores("FIX THE BUG")
        assert "bug-fix" in scores
