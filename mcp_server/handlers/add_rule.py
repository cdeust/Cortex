"""Handler: add_rule — add a neuro-symbolic rule to the memory system.

Rules are stored in the memory_rules table and applied during recall (via
mcp_server.core.memory_rules.apply_rules, invoked from
mcp_server.handlers.recall._apply_rules_and_order on every recall) to
hard-exclude, soft-rerank, or tag results. condition/action strings MUST use
the grammar mcp_server.core.memory_rules actually parses — see that
module's docstring for the canonical syntax. This handler is a thin
persistence layer over that grammar: it validates via
`memory_rules.validate_rule` before insert and never invents its own
condition/action syntax (a prior version of this docstring described a
'matcher:value' / 'exclude' shorthand no parser ever implemented; rules
created with it were silently inert at recall time — see the
fix/add-rule-memory-rules-drift RCA).

Rule types:
  - hard:  EXCLUDE memories whose condition matches (action must be "filter")
  - soft:  boost or penalize matching memories (action = "boost:N" | "penalty:N")
  - tag:   attach a tag to matching memories (action = "tag:NAME")

Scopes:
  - global:   applies everywhere
  - domain:   applies only within a named domain (scope_value = domain name)
  - directory: applies within a project directory
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.memory_rules import validate_rule
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE

# ── Schema ────────────────────────────────────────────────────────────────────

schema = {
    "title": "Add rule",
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Insert a neuro-symbolic rule into memory_rules so the "
        "`apply_rules` engine applies it on every subsequent recall — "
        "hard rules EXCLUDE matching memories, soft rules boost/penalize "
        "their rank, tag rules attach a tag. condition is '<field> <operator> "
        "<value>' (operators: ==, !=, contains, not_contains, >, <, >=, <=, "
        "matches — field may be a memory attribute like importance/heat, or "
        "'tag'/'tags' to match against the tags list). action is 'filter' "
        "(hard only), 'boost:<float>' or 'penalty:<float>' (soft only), or "
        "'tag:<name>' (tag only). Rejected outright (created=False) if the "
        "condition or action does not parse, or if the action's mechanism "
        "does not match rule_type. Scopes: global, domain, directory; "
        "resolved by priority then specificity. Use this to encode operating "
        "principles like `never surface deprecated memories` "
        "(condition='tag contains deprecated', action='filter', "
        "rule_type='hard') or `boost lessons in the recall pipeline` "
        "(condition='tag contains lesson', action='boost:0.3', "
        "rule_type='soft'). Distinct from `create_trigger` (proactive "
        "prospective memory, fires on context match — not a recall filter), "
        "and from `anchor` (per-memory pin, not a population rule). Mutates "
        "the memory_rules table; effect is visible at the next `recall` "
        "call. Latency ~20ms. Returns {rule_id, condition, action, scope, "
        "priority}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["condition", "action"],
        "properties": {
            "condition": {
                "type": "string",
                "description": (
                    "Rule condition as '<field> <operator> <value>' (e.g. "
                    "'tag contains deprecated', 'importance > 0.7', "
                    "'domain == old_project'). Operators: ==, !=, contains, "
                    "not_contains, >, <, >=, <=, matches (glob)."
                ),
                "examples": [
                    "tag contains deprecated",
                    "content contains TODO",
                    "domain == auth-service",
                ],
            },
            "action": {
                "type": "string",
                "description": (
                    "Action to perform when the condition matches. "
                    "'filter' excludes the memory (hard rules only); "
                    "'boost:N' / 'penalty:N' adjusts ranking by N (soft "
                    "rules only); 'tag:NAME' attaches a tag (tag rules only)."
                ),
                "examples": ["filter", "boost:0.3", "penalty:0.5", "tag:review"],
            },
            "rule_type": {
                "type": "string",
                "description": (
                    "Mechanism: 'hard' = filter results, 'soft' = rerank, "
                    "'tag' = attach metadata."
                ),
                "enum": ["hard", "soft", "tag"],
                "default": "soft",
                "examples": ["hard", "soft"],
            },
            "scope": {
                "type": "string",
                "description": (
                    "Where the rule applies: 'global' = everywhere; "
                    "'domain' = one cognitive domain (set scope_value); "
                    "'directory' = one project directory (set scope_value)."
                ),
                "enum": ["global", "domain", "directory"],
                "default": "global",
                "examples": ["global", "domain"],
            },
            "scope_value": {
                "type": "string",
                "description": (
                    "Domain id or absolute directory path. Required when scope is "
                    "'domain' or 'directory'."
                ),
                "examples": ["cortex", "/Users/alice/code/cortex"],
            },
            "priority": {
                "type": "integer",
                "description": (
                    "Higher priority rules apply first. Use to break ties among "
                    "overlapping rules."
                ),
                "default": 0,
                "minimum": -100,
                "maximum": 100,
                "examples": [0, 10, 50],
            },
            "source_memory_id": {
                "type": "integer",
                "description": (
                    "M-D6: the id of the lesson memory this rule was "
                    "promoted from, when created via a `lesson_promotion` "
                    "job. Omit for rules created directly (not through a "
                    "promotion job). Stored as memory_rules."
                    "source_memory_id — an unenforced pointer (no FK), "
                    "queryable both ways with the lesson's own "
                    "'promoted:rule' tag."
                ),
                "examples": [4198018],
            },
        },
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Handler ───────────────────────────────────────────────────────────────────


def _validate_rule_args(args: dict[str, Any]) -> dict[str, Any] | None:
    """Validate rule arguments. Returns error dict on failure, None on success.

    Precondition: `args` is the raw MCP tool-call argument dict.
    Postcondition: returns None iff every field is well-formed AND
    condition/action parse under mcp_server.core.memory_rules' grammar for
    the given rule_type (delegated to `validate_rule` — the single grammar
    authority; this function does not re-implement or shadow that parsing).
    Structural checks (presence, enum membership, scope_value requirement)
    run first so grammar errors are only reported once the shape is sane.
    """
    condition = (args.get("condition") or "").strip()
    if not condition:
        return {"created": False, "reason": "condition is required"}

    action = (args.get("action") or "").strip()
    if not action:
        return {"created": False, "reason": "action is required"}

    rule_type = args.get("rule_type", "soft")
    if rule_type not in ("hard", "soft", "tag"):
        return {"created": False, "reason": f"invalid rule_type: {rule_type}"}

    scope = args.get("scope", "global")
    if scope not in ("global", "domain", "directory"):
        return {"created": False, "reason": f"invalid scope: {scope}"}

    scope_value = (args.get("scope_value") or "").strip() or None
    if scope in ("domain", "directory") and not scope_value:
        return {"created": False, "reason": f"scope_value required when scope={scope}"}

    grammar_errors = validate_rule(rule_type, condition, action)
    if grammar_errors:
        return {"created": False, "reason": "; ".join(grammar_errors)}

    return None


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add a neuro-symbolic rule."""
    args = args or {}

    error = _validate_rule_args(args)
    if error is not None:
        return error

    condition = (args.get("condition") or "").strip()
    action = (args.get("action") or "").strip()
    rule_type = args.get("rule_type", "soft")
    scope = args.get("scope", "global")
    scope_value = (args.get("scope_value") or "").strip() or None
    priority = int(args.get("priority", 0))
    source_memory_id = args.get("source_memory_id")

    rule_id = _get_store().insert_rule(
        {
            "rule_type": rule_type,
            "scope": scope,
            "scope_value": scope_value,
            "condition": condition,
            "action": action,
            "priority": priority,
            "is_active": True,
            "source_memory_id": source_memory_id,
        }
    )

    return {
        "created": True,
        "rule_id": rule_id,
        "rule_type": rule_type,
        "scope": scope,
        "scope_value": scope_value,
        "condition": condition,
        "action": action,
        "priority": priority,
        "source_memory_id": source_memory_id,
    }
