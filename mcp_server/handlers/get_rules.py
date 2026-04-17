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
    "description": (
        "Enumerate active neuro-symbolic rules in the memory_rules table, "
        "optionally filtered by scope (global/domain/directory) or "
        "rule_type (hard=filter, soft=rerank, tag=attach metadata). Use "
        "this to audit which rules are shaping recall before adding a new "
        "one or debugging unexpected results. Distinct from `add_rule` "
        "(creates), `forget` (deletes a memory, not a rule), and "
        "`get_methodology_graph` (cognitive graph, not the rules table). "
        "Read-only. Latency ~30ms. Returns {rules: [{id, scope, "
        "scope_value, rule_type, condition, action, priority, active, "
        "created_at}]}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "scope": {
                "type": "string",
                "description": (
                    "Restrict to rules at a single scope. 'global' applies "
                    "everywhere; 'domain' applies to one cognitive domain; "
                    "'directory' applies to one project directory. Omit for all scopes."
                ),
                "enum": ["global", "domain", "directory"],
                "examples": ["global", "domain"],
            },
            "rule_type": {
                "type": "string",
                "description": (
                    "Restrict by rule mechanism: 'hard' = filter results, "
                    "'soft' = rerank, 'tag' = attach metadata. Omit for all types."
                ),
                "enum": ["hard", "soft", "tag"],
                "examples": ["hard", "soft"],
            },
            "include_inactive": {
                "type": "boolean",
                "description": "Include rules that have been deactivated (default omits them).",
                "default": False,
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
        with store.acquire_interactive() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_rules ORDER BY scope, priority DESC"
            ).fetchall()
        rules = [dict(r) for r in rows]

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
