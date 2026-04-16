"""Handler: add_rule — add a neuro-symbolic rule to the memory system.

Rules are stored in the memory_rules table and applied during recall to
hard-filter or soft-rerank results.

Rule types:
  - hard:  exclude memories matching the condition from results
  - soft:  boost or penalize matching memories (action = "boost" | "penalize")
  - tag:   apply a tag to matching memories on retrieval

Scopes:
  - global:   applies everywhere
  - domain:   applies only within a named domain (scope_value = domain name)
  - directory: applies within a project directory
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────────

schema = {
    "description": (
        "Insert a neuro-symbolic rule into memory_rules so the "
        "`apply_rules` engine applies it on every subsequent recall — "
        "hard-filter (exclude), soft-rerank "
        "(boost/penalize), or tag the matching memories. Conditions match "
        "on tags / keywords / metadata; actions specify the effect. Scopes: "
        "global, domain, directory; resolved by priority then specificity. "
        "Use this to encode operating principles like `never surface "
        "deprecated memories` or `boost lessons in the recall pipeline`. "
        "Distinct from `create_trigger` (proactive prospective memory, "
        "fires on context match — not a recall filter), and from `anchor` "
        "(per-memory pin, not a population rule). Mutates the memory_rules "
        "table; effect is visible at the next `recall` call. Latency "
        "~20ms. Returns {rule_id, condition, action, scope, priority}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["condition", "action"],
        "properties": {
            "condition": {
                "type": "string",
                "description": (
                    "Rule condition expressed as 'matcher:value' (e.g. "
                    "'tag:deprecated', 'domain:old_project', 'keyword:secret', "
                    "'source:import')."
                ),
                "examples": ["tag:deprecated", "keyword:TODO", "domain:auth-service"],
            },
            "action": {
                "type": "string",
                "description": (
                    "Action to perform when the condition matches. "
                    "'exclude' filters out (hard); 'boost:N' / 'penalize:N' "
                    "adjusts ranking by N (soft); 'tag:NAME' attaches a tag (tag rule)."
                ),
                "examples": ["exclude", "boost:0.3", "penalize:0.5", "tag:review"],
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
                "description": "Domain id or absolute directory path. Required when scope is 'domain' or 'directory'.",
                "examples": ["cortex", "/Users/alice/code/cortex"],
            },
            "priority": {
                "type": "integer",
                "description": "Higher priority rules apply first. Use to break ties among overlapping rules.",
                "default": 0,
                "minimum": -100,
                "maximum": 100,
                "examples": [0, 10, 50],
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
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Handler ───────────────────────────────────────────────────────────────────


def _validate_rule_args(args: dict[str, Any]) -> dict[str, Any] | None:
    """Validate rule arguments. Returns error dict on failure, None on success."""
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

    rule_id = _get_store().insert_rule(
        {
            "rule_type": rule_type,
            "scope": scope,
            "scope_value": scope_value,
            "condition": condition,
            "action": action,
            "priority": priority,
            "is_active": True,
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
    }
