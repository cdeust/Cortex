"""Neuro-symbolic rules engine — hard constraints and soft preferences over retrieval.

Implements condition parsing (field, operator, value) and evaluation against
memory dicts. Hard rules EXCLUDE matching memories, soft rules boost/penalize
retrieval scores, tag rules attach a tag to matching memories.

This module is the single grammar authority for rule text: `add_rule`
(mcp_server/handlers/add_rule.py) MUST accept only condition/action strings
this module can parse — enforced by calling `validate_rule` at write time.
Canonical syntax:
    condition: "<field> <operator> <value>", operator in VALID_OPERATORS.
        e.g. "importance > 0.7", "tag contains deprecated".
    action:    "filter" (hard rules only) | "boost:<float>" | "penalty:<float>"
               (soft rules only) | "tag:<name>" (tag rules only).

Pure business logic — no I/O. Rule storage is handled by the caller.
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Valid condition operators
VALID_OPERATORS = frozenset(
    {
        "==",
        "!=",
        "contains",
        "not_contains",
        ">",
        "<",
        ">=",
        "<=",
        "matches",
    }
)

# Fields that use numeric comparison
NUMERIC_FIELDS = frozenset(
    {
        "heat",
        "importance",
        "surprise_score",
        "confidence",
        "emotional_valence",
        "plasticity",
        "stability",
        "excitability",
        "access_count",
        "useful_count",
        "compression_level",
        "reconsolidation_count",
    }
)


def parse_condition(condition: str) -> tuple[str, str, str]:
    """Parse a condition string into (field, operator, value).

    Examples:
        "importance > 0.7"  → ("importance", ">", "0.7")
        "tag contains architecture" → ("tag", "contains", "architecture")
        "content not_contains password" → ("content", "not_contains", "password")
        "directory_context matches /project/*" →
            ("directory_context", "matches", "/project/*")

    Raises ValueError if condition cannot be parsed.
    """
    # Multi-word operators first
    for op in ("not_contains",):
        if f" {op} " in condition:
            parts = condition.split(f" {op} ", 1)
            return parts[0].strip(), op, parts[1].strip()

    # Two-char operators
    for op in (">=", "<=", "==", "!="):
        if f" {op} " in condition:
            parts = condition.split(f" {op} ", 1)
            return parts[0].strip(), op, parts[1].strip()

    # Single-char operators
    for op in (">", "<"):
        if f" {op} " in condition:
            parts = condition.split(f" {op} ", 1)
            return parts[0].strip(), op, parts[1].strip()

    # Word operators
    for op in ("contains", "matches"):
        if f" {op} " in condition:
            parts = condition.split(f" {op} ", 1)
            return parts[0].strip(), op, parts[1].strip()

    raise ValueError(f"Cannot parse condition: {condition!r}")  # noqa: TRY003 — one-off message, not reused (§3.3)


def parse_action(action: str) -> tuple[str, float | str]:
    """Parse an action string into (action_type, value).

    "filter"      → ("filter", 0.0)
    "boost:0.3"   → ("boost", 0.3)
    "penalty:0.2" → ("penalty", 0.2)
    "tag:review"  → ("tag", "review")

    Raises ValueError on invalid action, or on "tag:" with an empty name.
    """
    if action == "filter":
        return "filter", 0.0
    if action.startswith("boost:"):
        return "boost", float(action.split(":", 1)[1])
    if action.startswith("penalty:"):
        return "penalty", float(action.split(":", 1)[1])
    if action.startswith("tag:"):
        tag_name = action.split(":", 1)[1].strip()
        if not tag_name:
            raise ValueError(f"tag action requires a non-empty name: {action!r}")  # noqa: TRY003 — one-off message, not reused (§3.3)
        return "tag", tag_name
    raise ValueError(f"Invalid action: {action!r}")  # noqa: TRY003 — one-off message, not reused (§3.3)


def get_field_value(memory: dict, field: str) -> Any:
    """Get a field value from a memory dict.

    Supports direct fields plus 'tag'/'tags' which checks the tags list,
    and tag-key:value pairs (e.g., "language" checks for "language:python" tags).
    """
    if field in ("tag", "tags"):
        return memory.get("tags", [])
    if field in memory:
        return memory[field]
    # Check for key:value tags
    tags = memory.get("tags", [])
    if isinstance(tags, list):
        for tag in tags:
            if ":" in tag:
                key, val = tag.split(":", 1)
                if key.strip() == field:
                    return val.strip()
            elif "=" in tag:
                key, val = tag.split("=", 1)
                if key.strip() == field:
                    return val.strip()
    return None


def _evaluate_numeric(field_value: Any, operator: str, value: str) -> bool:
    """Evaluate numeric comparison operators (>, <, >=, <=)."""
    try:
        num_field = (
            float(field_value)
            if not isinstance(field_value, (int, float))
            else field_value
        )
        num_value = float(value)
    except (ValueError, TypeError):
        return False
    ops = {
        ">": num_field > num_value,
        "<": num_field < num_value,
        ">=": num_field >= num_value,
        "<=": num_field <= num_value,
    }
    return ops[operator]


def _evaluate_equality(field: str, field_value: Any, operator: str, value: str) -> bool:
    """Evaluate == and != operators, with numeric fallback for numeric fields."""
    is_equal = operator == "=="
    if field in NUMERIC_FIELDS:
        try:
            result = float(field_value) == float(value)
        except (ValueError, TypeError):
            pass
        else:
            return result if is_equal else not result
    str_match = str(field_value).lower() == str(value).lower()
    return str_match if is_equal else not str_match


def _evaluate_contains(field_value: Any, value: str, negate: bool) -> bool:
    """Evaluate contains / not_contains operators."""
    if isinstance(field_value, list):
        found = any(value.lower() in str(item).lower() for item in field_value)
    else:
        found = value.lower() in str(field_value).lower()
    return not found if negate else found


def evaluate_condition(condition: str, memory: dict) -> bool:
    """Evaluate a parsed condition against a memory dict.

    Precondition: `condition` is any string (parseable or not); `memory` is a
    dict, possibly missing the referenced field.
    Postcondition: returns True iff the condition parses AND the memory
    satisfies it. An unparseable condition never matches (returns False) —
    this is the read-side fail-safe: a malformed rule (which should not
    exist post `validate_rule`, but may for legacy data written before that
    gate existed) degrades to a silent no-op rather than, under hard-rule
    semantics, excluding every memory from every recall. The parse failure
    is logged so operators can find and repair the offending row.
    """
    try:
        field, operator, value = parse_condition(condition)
    except ValueError:
        logger.warning(
            "memory_rules: unparseable condition %r — rule is a no-op", condition
        )
        return False

    field_value = get_field_value(memory, field)
    if field_value is None:
        field_value = 0.0 if operator in (">", "<", ">=", "<=") else ""

    if operator in (">", "<", ">=", "<="):
        return _evaluate_numeric(field_value, operator, value)
    if operator in ("==", "!="):
        return _evaluate_equality(field, field_value, operator, value)
    if operator == "contains":
        return _evaluate_contains(field_value, value, negate=False)
    if operator == "not_contains":
        return _evaluate_contains(field_value, value, negate=True)
    if operator == "matches":
        return fnmatch.fnmatch(str(field_value), value)
    return True


def _apply_soft_rule(
    memories: list[dict],
    condition: str,
    action: str,
    score_field: str,
) -> None:
    """Apply a soft rule's boost/penalty to matching memories in-place."""
    try:
        action_type, action_value = parse_action(action)
    except ValueError:
        return
    if action_type not in ("boost", "penalty"):
        return
    for m in memories:
        if evaluate_condition(condition, m):
            score = m.get(score_field, 0.0)
            if action_type == "boost":
                m[score_field] = score + action_value
            elif action_type == "penalty":
                m[score_field] = score - action_value


def _apply_tag_rule(memories: list[dict], condition: str, action: str) -> None:
    """Attach a tag to every memory matching `condition`, in-place, deduped."""
    try:
        action_type, tag_name = parse_action(action)
    except ValueError:
        return
    if action_type != "tag":
        return
    for m in memories:
        if evaluate_condition(condition, m):
            tags = m.setdefault("tags", [])
            if tag_name not in tags:
                tags.append(tag_name)


def apply_rules(
    memories: list[dict],
    rules: list[dict],
    score_field: str = "score",
) -> list[dict]:
    """Apply rules to filter, re-rank, and tag a list of memories.

    Precondition: `memories` is a list of memory dicts, each carrying
    `score_field` (missing → treated as 0.0); `rules` is a list of rule
    dicts as returned by MemoryStore.get_all_active_rules() — each with
    rule_type/condition/action; rules with an empty condition are skipped.
    Postcondition: the returned list contains every input memory whose
    matching hard rules (rule_type="hard") did NOT match its condition —
    i.e. a hard rule EXCLUDES memories that satisfy its condition (matches
    add_rule's documented "never surface deprecated memories" semantics: the
    condition names what you want gone, the rule removes it). Soft rules
    (rule_type="soft") only adjust `score_field` on matching memories via
    boost/penalty and never change membership. Tag rules (rule_type="tag")
    only append a tag to matching memories' "tags" list and never change
    membership or score. The result is sorted descending by `score_field`.
    Invariant across the rule loop: `len(result) <= len(memories)` (only
    hard rules can shrink the list; soft/tag rules are membership-preserving).

    Args:
        memories: List of memory dicts (must have `score_field`).
        rules: List of rule dicts with rule_type, condition, action.
        score_field: Name of the score field to adjust.

    Returns:
        Filtered, re-ranked, and tag-annotated list.
    """
    result = list(memories)

    for rule in rules:
        rule_type = rule.get("rule_type", "soft")
        condition = rule.get("condition", "")
        if not condition:
            continue

        if rule_type == "hard":
            # Exclude memories that MATCH the condition (see postcondition above).
            result = [m for m in result if not evaluate_condition(condition, m)]
        elif rule_type == "soft":
            _apply_soft_rule(result, condition, rule.get("action", ""), score_field)
        elif rule_type == "tag":
            _apply_tag_rule(result, condition, rule.get("action", ""))

    result.sort(key=lambda m: m.get(score_field, 0.0), reverse=True)
    return result


def validate_rule(
    rule_type: str,
    condition: str,
    action: str,
) -> list[str]:
    """Validate a rule definition before it is persisted.

    Precondition: none — inputs may be arbitrary strings.
    Postcondition: returns the empty list iff `condition` is parseable by
    parse_condition, `action` is parseable by parse_action, and the action's
    mechanism matches rule_type (hard→filter, soft→boost/penalty,
    tag→tag:name). This is the fail-closed write-time gate: it is the only
    place a rule is rejected outright; evaluate_condition's read-time
    behavior on unparseable conditions is deliberately permissive (see its
    docstring) precisely because this gate is expected to prevent
    unparseable conditions from ever reaching storage in the first place.
    """
    errors: list[str] = []

    if rule_type not in ("hard", "soft", "tag"):
        errors.append(f"rule_type must be 'hard', 'soft' or 'tag', got {rule_type!r}")

    try:
        parse_condition(condition)
    except ValueError as e:
        errors.append(str(e))

    try:
        action_type, _ = parse_action(action)
        if rule_type == "hard" and action_type != "filter":
            errors.append("Hard rules must use 'filter' action")
        if rule_type == "soft" and action_type not in ("boost", "penalty"):
            errors.append("Soft rules must use 'boost:N' or 'penalty:N' action")
        if rule_type == "tag" and action_type != "tag":
            errors.append("Tag rules must use 'tag:NAME' action")
    except ValueError as e:
        errors.append(str(e))

    return errors
