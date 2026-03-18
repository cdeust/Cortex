"""Neuro-symbolic rules engine — hard constraints and soft preferences over retrieval.

Implements condition parsing (field, operator, value) and evaluation against
memory dicts. Hard rules filter, soft rules boost/penalize retrieval scores.

Pure business logic — no I/O. Rule storage is handled by the caller.

Pure business logic -- no I/O.
"""

from __future__ import annotations

import fnmatch
from typing import Any

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
        "directory_context matches /project/*" → ("directory_context", "matches", "/project/*")

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

    raise ValueError(f"Cannot parse condition: {condition!r}")


def parse_action(action: str) -> tuple[str, float]:
    """Parse an action string into (action_type, value).

    "filter"     → ("filter", 0.0)
    "boost:0.3"  → ("boost", 0.3)
    "penalty:0.2"→ ("penalty", 0.2)

    Raises ValueError on invalid action.
    """
    if action == "filter":
        return "filter", 0.0
    if action.startswith("boost:"):
        return "boost", float(action.split(":", 1)[1])
    if action.startswith("penalty:"):
        return "penalty", float(action.split(":", 1)[1])
    raise ValueError(f"Invalid action: {action!r}")


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
            return result if is_equal else not result
        except (ValueError, TypeError):
            pass
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

    Returns True if the condition is satisfied.
    Returns True on parse errors (fail open).
    """
    try:
        field, operator, value = parse_condition(condition)
    except ValueError:
        return True

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
    for m in memories:
        if evaluate_condition(condition, m):
            score = m.get(score_field, 0.0)
            if action_type == "boost":
                m[score_field] = score + action_value
            elif action_type == "penalty":
                m[score_field] = score - action_value


def apply_rules(
    memories: list[dict],
    rules: list[dict],
    score_field: str = "score",
) -> list[dict]:
    """Apply rules to filter and re-rank a list of memories.

    Hard rules (rule_type="hard") filter out non-matching memories.
    Soft rules (rule_type="soft") adjust the score field via boost/penalty.

    Args:
        memories: List of memory dicts (must have `score_field`).
        rules: List of rule dicts with rule_type, condition, action.
        score_field: Name of the score field to adjust.

    Returns:
        Filtered and re-ranked list.
    """
    result = list(memories)

    for rule in rules:
        rule_type = rule.get("rule_type", "soft")
        condition = rule.get("condition", "")
        if not condition:
            continue

        if rule_type == "hard":
            result = [m for m in result if evaluate_condition(condition, m)]
        elif rule_type == "soft":
            _apply_soft_rule(result, condition, rule.get("action", ""), score_field)

    result.sort(key=lambda m: m.get(score_field, 0.0), reverse=True)
    return result


def validate_rule(
    rule_type: str,
    condition: str,
    action: str,
) -> list[str]:
    """Validate a rule definition. Returns list of error messages (empty = valid)."""
    errors: list[str] = []

    if rule_type not in ("hard", "soft"):
        errors.append(f"rule_type must be 'hard' or 'soft', got {rule_type!r}")

    try:
        parse_condition(condition)
    except ValueError as e:
        errors.append(str(e))

    try:
        action_type, _ = parse_action(action)
        if rule_type == "hard" and action_type != "filter":
            errors.append("Hard rules must use 'filter' action")
    except ValueError as e:
        errors.append(str(e))

    return errors
