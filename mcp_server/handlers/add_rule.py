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
    "description": "Add a neuro-symbolic rule to the memory store. Rules hard-filter or soft-rerank recall results based on conditions.",
    "inputSchema": {
        "type": "object",
        "required": ["condition", "action"],
        "properties": {
            "condition": {
                "type": "string",
                "description": "Rule condition (e.g. 'tag:deprecated', 'domain:old_project', 'keyword:secret')",
            },
            "action": {
                "type": "string",
                "description": "Rule action (e.g. 'exclude', 'boost:0.3', 'penalize:0.5', 'tag:review')",
            },
            "rule_type": {
                "type": "string",
                "enum": ["hard", "soft", "tag"],
                "description": "Rule type: hard (filter), soft (rerank), tag (label). Default: soft",
            },
            "scope": {
                "type": "string",
                "enum": ["global", "domain", "directory"],
                "description": "Scope where rule applies. Default: global",
            },
            "scope_value": {
                "type": "string",
                "description": "Domain name or directory path when scope is domain/directory",
            },
            "priority": {
                "type": "integer",
                "description": "Rule priority (higher = applied first). Default: 0",
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
