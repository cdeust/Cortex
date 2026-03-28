"""Handler: get_rules — list active neuro-symbolic rules.

Returns rules stored in the memory_rules table, optionally filtered
by scope or rule type.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────────

schema = {
    "description": "List active neuro-symbolic rules in the memory store, optionally filtered by scope or rule type.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["global", "domain", "directory"],
                "description": "Filter by scope (default: all scopes)",
            },
            "rule_type": {
                "type": "string",
                "enum": ["hard", "soft", "tag"],
                "description": "Filter by rule type (default: all types)",
            },
            "include_inactive": {
                "type": "boolean",
                "description": "Include deactivated rules (default false)",
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


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """List active neuro-symbolic rules."""
    args = args or {}
    scope_filter = args.get("scope")
    type_filter = args.get("rule_type")
    include_inactive = bool(args.get("include_inactive", False))

    store = _get_store()

    if scope_filter:
        rules = store.get_rules_for_scope(scope_filter)
    else:
        rules = store.get_all_active_rules()

    # Include inactive if requested
    if include_inactive and not scope_filter:
        from mcp_server.infrastructure.sql_compat import fetchall

        rules = fetchall(store._conn,
            "SELECT * FROM memory_rules ORDER BY scope, priority DESC"
        )

    # Filter by rule_type if requested
    if type_filter:
        rules = [r for r in rules if r.get("rule_type") == type_filter]

    by_scope: dict[str, list] = {}
    for rule in rules:
        s = rule.get("scope", "global")
        by_scope.setdefault(s, []).append(rule)

    return {
        "total": len(rules),
        "rules": rules,
        "by_scope": {k: len(v) for k, v in by_scope.items()},
    }
