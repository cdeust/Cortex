"""Tests for core/wiki_rule_engine — user-editable classifier rules.

The engine's contract: given memory content + tags and the rules parsed
from ``wiki/_rules/*.md``, return the first matching rule's target kind,
None-target for an explicit rejection, and a no-match result the caller
can fall back from. Every matcher kind and every no-match arm is pinned,
including the invalid-regex failure path (its observable effect is
"rule silently does not match" — asserted as such).
"""

from __future__ import annotations

from mcp_server.core.wiki_rule_engine import apply_rules
from mcp_server.shared.wiki_schema_loader import ClassifierRule


def _rule(
    pattern: str,
    pattern_kind: str,
    target_kind: str | None,
    weight: float = 1.0,
) -> ClassifierRule:
    return ClassifierRule(
        pattern=pattern,
        pattern_kind=pattern_kind,
        target_kind=target_kind,
        weight=weight,
    )


# ── Matcher kinds ─────────────────────────────────────────────────────


def test_prefix_match_is_case_insensitive_and_ignores_leading_space():
    match = apply_rules(
        "  The bug was in the parser", None, [_rule("the bug", "prefix", "adr")]
    )
    assert match.target_kind == "adr"
    assert match.matched_rule is not None


def test_prefix_only_matches_the_start():
    match = apply_rules("we found the bug", None, [_rule("the bug", "prefix", "adr")])
    assert match.matched_rule is None


def test_substring_match_is_case_insensitive():
    match = apply_rules(
        "Deployed THE Fix today", None, [_rule("the fix", "substring", "note")]
    )
    assert match.target_kind == "note"


def test_regex_match_is_case_insensitive():
    match = apply_rules(
        "Error Code 42 raised", None, [_rule(r"error code \d+", "regex", "spec")]
    )
    assert match.target_kind == "spec"


def test_invalid_regex_silently_does_not_match():
    match = apply_rules("anything", None, [_rule("([unclosed", "regex", "spec")])
    assert match.matched_rule is None
    assert match.rationale == "no rule matched"


def test_tag_match_is_case_insensitive():
    match = apply_rules("content", ["ADR", 42, None], [_rule("adr", "tag", "adr")])
    assert match.target_kind == "adr", "non-string tags are ignored, not fatal"


def test_empty_pattern_never_matches():
    match = apply_rules("content", None, [_rule("", "substring", "note")])
    assert match.matched_rule is None


def test_unknown_pattern_kind_never_matches():
    match = apply_rules("content", None, [_rule("content", "glob", "note")])
    assert match.matched_rule is None


# ── Selection order ───────────────────────────────────────────────────


def test_first_matching_rule_wins_over_later_heavier_rules():
    rules = [
        _rule("content", "substring", "note", weight=1.0),
        _rule("content", "substring", "spec", weight=99.0),
    ]
    match = apply_rules("content here", None, rules)
    assert match.target_kind == "note", "file order beats weight across rows"


def test_non_matching_rules_are_skipped_to_the_first_match():
    rules = [
        _rule("absent", "substring", "note"),
        _rule("present", "substring", "spec"),
    ]
    match = apply_rules("the word present appears", None, rules)
    assert match.target_kind == "spec"


# ── Rejection and fallback arms ───────────────────────────────────────


def test_reject_target_returns_matched_rule_with_none_kind():
    match = apply_rules("spam content", None, [_rule("spam", "substring", "reject")])
    assert match.matched_rule is not None
    assert match.target_kind is None
    assert "reject" in match.rationale


def test_dash_and_none_targets_also_reject():
    for target in ("-", "", None, "none"):
        match = apply_rules("spam", None, [_rule("spam", "substring", target)])
        assert match.target_kind is None, f"target {target!r} must reject"


def test_empty_content_falls_back_without_evaluating_rules():
    match = apply_rules("", None, [_rule("x", "substring", "note")])
    assert match.matched_rule is None
    assert match.rationale == "no content or no rules loaded"


def test_no_rules_falls_back():
    match = apply_rules("content", ["tag"], [])
    assert match.matched_rule is None
    assert match.rationale == "no content or no rules loaded"


def test_rationale_names_the_matched_pattern_and_target():
    match = apply_rules("the bug was", None, [_rule("the bug", "prefix", "adr")])
    assert "[prefix]" in match.rationale
    assert "'the bug'" in match.rationale
    assert "adr" in match.rationale
