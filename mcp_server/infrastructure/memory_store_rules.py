"""Rule CRUD mixin for MemoryStore."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


class MemoryRuleMixin:
    """Memory rule persistence operations.

    Requires _conn (sqlite3.Connection) and _row_to_dict on the host class.
    """

    _conn: sqlite3.Connection

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def insert_rule(self, data: dict[str, Any]) -> int:
        now = self._now_iso()
        cursor = self._conn.execute(
            "INSERT INTO memory_rules "
            "(rule_type, scope, scope_value, condition, action, priority, "
            "is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.get("rule_type", "soft"),
                data.get("scope", "global"),
                data.get("scope_value"),
                data["condition"],
                data["action"],
                data.get("priority", 0),
                1 if data.get("is_active", True) else 0,
                now,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_rules_for_scope(self, scope: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memory_rules WHERE scope = ? AND is_active = 1 "
            "ORDER BY priority DESC",
            (scope,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_all_active_rules(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memory_rules WHERE is_active = 1 "
            "ORDER BY scope, priority DESC"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_rule(self, rule_id: int, updates: dict[str, Any]) -> None:
        allowed = (
            "rule_type",
            "scope",
            "scope_value",
            "condition",
            "action",
            "priority",
            "is_active",
        )
        sets = []
        vals: list[Any] = []
        for k, v in updates.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                vals.append(v)
        if sets:
            vals.append(rule_id)
            self._conn.execute(
                f"UPDATE memory_rules SET {', '.join(sets)} WHERE id = ?",
                tuple(vals),
            )
            self._conn.commit()
