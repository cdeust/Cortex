"""Rule CRUD mixin for PgMemoryStore."""

from __future__ import annotations

from typing import Any

import psycopg


class PgRuleMixin:
    """Memory rule persistence operations on PostgreSQL."""

    _conn: psycopg.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by PgMemoryStore."""
        return dict(row)

    def insert_rule(self, data: dict[str, Any]) -> int:
        row = self._conn.execute(
            "INSERT INTO memory_rules "
            "(rule_type, scope, scope_value, condition, action, priority, "
            "is_active, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW()) RETURNING id",
            (
                data.get("rule_type", "soft"),
                data.get("scope", "global"),
                data.get("scope_value"),
                data["condition"],
                data["action"],
                data.get("priority", 0),
                data.get("is_active", True),
            ),
        ).fetchone()
        self._conn.commit()
        return row["id"]

    def get_rules_for_scope(self, scope: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memory_rules WHERE scope = %s AND is_active "
            "ORDER BY priority DESC",
            (scope,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_active_rules(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memory_rules WHERE is_active "
            "ORDER BY scope, priority DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_rule(self, rule_id: int, updates: dict[str, Any]) -> None:
        allowed = {
            "rule_type", "scope", "scope_value",
            "condition", "action", "priority", "is_active",
        }
        sets = []
        vals: list[Any] = []
        for k, v in updates.items():
            if k in allowed:
                sets.append(f"{k} = %s")
                vals.append(v)
        if sets:
            vals.append(rule_id)
            self._conn.execute(
                f"UPDATE memory_rules SET {', '.join(sets)} WHERE id = %s",
                tuple(vals),
            )
            self._conn.commit()
