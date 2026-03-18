"""Tests for mcp_server.core.memory_rules — neuro-symbolic rules engine."""

import pytest

from mcp_server.core.memory_rules import (
    parse_condition,
    parse_action,
    get_field_value,
    evaluate_condition,
    apply_rules,
    validate_rule,
)


class TestParseCondition:
    def test_greater_than(self):
        assert parse_condition("importance > 0.7") == ("importance", ">", "0.7")

    def test_less_than(self):
        assert parse_condition("heat < 0.1") == ("heat", "<", "0.1")

    def test_equals(self):
        assert parse_condition("domain == testing") == ("domain", "==", "testing")

    def test_not_equals(self):
        assert parse_condition("store_type != semantic") == (
            "store_type",
            "!=",
            "semantic",
        )

    def test_contains(self):
        assert parse_condition("tag contains architecture") == (
            "tag",
            "contains",
            "architecture",
        )

    def test_not_contains(self):
        assert parse_condition("content not_contains password") == (
            "content",
            "not_contains",
            "password",
        )

    def test_matches(self):
        assert parse_condition("directory_context matches /project/*") == (
            "directory_context",
            "matches",
            "/project/*",
        )

    def test_gte(self):
        assert parse_condition("confidence >= 0.8") == ("confidence", ">=", "0.8")

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_condition("no operator here")


class TestParseAction:
    def test_filter(self):
        assert parse_action("filter") == ("filter", 0.0)

    def test_boost(self):
        assert parse_action("boost:0.3") == ("boost", 0.3)

    def test_penalty(self):
        assert parse_action("penalty:0.2") == ("penalty", 0.2)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_action("unknown_action")


class TestGetFieldValue:
    def test_direct_field(self):
        mem = {"heat": 0.8, "domain": "testing"}
        assert get_field_value(mem, "heat") == 0.8

    def test_tags_field(self):
        mem = {"tags": ["python", "core"]}
        assert get_field_value(mem, "tag") == ["python", "core"]

    def test_tag_key_value(self):
        mem = {"tags": ["language:python", "priority:high"]}
        assert get_field_value(mem, "language") == "python"

    def test_missing_field(self):
        assert get_field_value({}, "nonexistent") is None


class TestEvaluateCondition:
    def test_numeric_greater(self):
        mem = {"importance": 0.8}
        assert evaluate_condition("importance > 0.5", mem) is True
        assert evaluate_condition("importance > 0.9", mem) is False

    def test_numeric_less(self):
        mem = {"heat": 0.3}
        assert evaluate_condition("heat < 0.5", mem) is True

    def test_equality(self):
        mem = {"domain": "testing"}
        assert evaluate_condition("domain == testing", mem) is True
        assert evaluate_condition("domain == production", mem) is False

    def test_not_equals(self):
        mem = {"store_type": "episodic"}
        assert evaluate_condition("store_type != semantic", mem) is True

    def test_contains_string(self):
        mem = {"content": "Fix the memory leak"}
        assert evaluate_condition("content contains memory", mem) is True
        assert evaluate_condition("content contains database", mem) is False

    def test_contains_list(self):
        mem = {"tags": ["python", "architecture"]}
        assert evaluate_condition("tag contains architecture", mem) is True
        assert evaluate_condition("tag contains java", mem) is False

    def test_not_contains(self):
        mem = {"content": "public information"}
        assert evaluate_condition("content not_contains password", mem) is True
        assert evaluate_condition("content not_contains public", mem) is False

    def test_matches_glob(self):
        mem = {"directory_context": "/project/src/core"}
        assert evaluate_condition("directory_context matches /project/*", mem) is True
        assert evaluate_condition("directory_context matches /other/*", mem) is False

    def test_none_field_numeric(self):
        mem = {}
        assert evaluate_condition("importance > 0.5", mem) is False  # None → 0.0

    def test_unparseable_passes(self):
        assert evaluate_condition("gibberish", {}) is True


class TestApplyRules:
    def test_hard_filter(self):
        memories = [
            {"content": "important", "importance": 0.9, "score": 1.0},
            {"content": "trivial", "importance": 0.2, "score": 0.8},
        ]
        rules = [
            {"rule_type": "hard", "condition": "importance > 0.5", "action": "filter"}
        ]
        result = apply_rules(memories, rules)
        assert len(result) == 1
        assert result[0]["content"] == "important"

    def test_soft_boost(self):
        memories = [
            {"content": "a", "importance": 0.9, "score": 0.5},
            {"content": "b", "importance": 0.3, "score": 0.8},
        ]
        rules = [
            {
                "rule_type": "soft",
                "condition": "importance > 0.5",
                "action": "boost:0.5",
            }
        ]
        result = apply_rules(memories, rules)
        # "a" should now have score 1.0 and rank first
        assert result[0]["content"] == "a"
        assert result[0]["score"] == 1.0

    def test_soft_penalty(self):
        memories = [
            {"content": "a", "importance": 0.9, "score": 0.8},
            {"content": "b", "importance": 0.3, "score": 0.7},
        ]
        rules = [
            {
                "rule_type": "soft",
                "condition": "importance > 0.5",
                "action": "penalty:0.5",
            }
        ]
        result = apply_rules(memories, rules)
        # "a" penalized to 0.3, "b" stays at 0.7
        assert result[0]["content"] == "b"

    def test_empty_rules(self):
        memories = [{"content": "x", "score": 1.0}]
        assert apply_rules(memories, []) == memories

    def test_multiple_rules(self):
        memories = [
            {"content": "a", "heat": 0.9, "importance": 0.8, "score": 1.0},
            {"content": "b", "heat": 0.1, "importance": 0.2, "score": 0.9},
            {"content": "c", "heat": 0.5, "importance": 0.6, "score": 0.5},
        ]
        rules = [
            {"rule_type": "hard", "condition": "heat > 0.2", "action": "filter"},
            {
                "rule_type": "soft",
                "condition": "importance > 0.7",
                "action": "boost:0.5",
            },
        ]
        result = apply_rules(memories, rules)
        assert len(result) == 2  # "b" filtered out
        assert result[0]["content"] == "a"  # Boosted


class TestValidateRule:
    def test_valid_rule(self):
        errors = validate_rule("soft", "importance > 0.7", "boost:0.3")
        assert errors == []

    def test_invalid_type(self):
        errors = validate_rule("invalid", "importance > 0.7", "boost:0.3")
        assert len(errors) >= 1

    def test_invalid_condition(self):
        errors = validate_rule("soft", "no_operator", "boost:0.3")
        assert len(errors) >= 1

    def test_invalid_action(self):
        errors = validate_rule("soft", "importance > 0.7", "explode")
        assert len(errors) >= 1

    def test_hard_rule_must_filter(self):
        errors = validate_rule("hard", "importance > 0.7", "boost:0.3")
        assert any("filter" in e for e in errors)
