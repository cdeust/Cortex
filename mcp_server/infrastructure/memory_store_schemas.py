"""Schema (cortical knowledge structures) CRUD mixin for MemoryStore."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


class MemorySchemaMixin:
    """Schema persistence operations (Tse 2007 cortical structures).

    Requires _conn (sqlite3.Connection) on the host class.
    """

    _conn: sqlite3.Connection

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def insert_schema(self, data: dict[str, Any]) -> int:
        """Insert or update a schema."""
        now = self._now_iso()
        try:
            cursor = self._conn.execute(
                """INSERT INTO schemas (
                    schema_id, domain, label, entity_signature,
                    relationship_types, tag_signature,
                    consistency_threshold, formation_count,
                    assimilation_count, violation_count,
                    last_updated, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["schema_id"],
                    data.get("domain", ""),
                    data.get("label", ""),
                    json.dumps(data.get("entity_signature", {})),
                    json.dumps(data.get("relationship_types", [])),
                    json.dumps(data.get("tag_signature", {})),
                    data.get("consistency_threshold", 0.7),
                    data.get("formation_count", 0),
                    data.get("assimilation_count", 0),
                    data.get("violation_count", 0),
                    now,
                    data.get("created_at", now),
                ),
            )
            self._conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return self._update_existing_schema(data, now)

    def _update_existing_schema(self, data: dict[str, Any], now: str) -> int:
        """Update an existing schema by schema_id, return its row id."""
        self._conn.execute(
            """UPDATE schemas SET
                domain = ?, label = ?, entity_signature = ?,
                relationship_types = ?, tag_signature = ?,
                consistency_threshold = ?, formation_count = ?,
                assimilation_count = ?, violation_count = ?,
                last_updated = ?
            WHERE schema_id = ?""",
            (
                data.get("domain", ""),
                data.get("label", ""),
                json.dumps(data.get("entity_signature", {})),
                json.dumps(data.get("relationship_types", [])),
                json.dumps(data.get("tag_signature", {})),
                data.get("consistency_threshold", 0.7),
                data.get("formation_count", 0),
                data.get("assimilation_count", 0),
                data.get("violation_count", 0),
                now,
                data["schema_id"],
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM schemas WHERE schema_id = ?",
            (data["schema_id"],),
        ).fetchone()
        return row["id"] if row else 0

    def get_schemas_for_domain(self, domain: str) -> list[dict[str, Any]]:
        """Get all schemas for a domain."""
        rows = self._conn.execute(
            "SELECT * FROM schemas WHERE domain = ? ORDER BY formation_count DESC",
            (domain,),
        ).fetchall()
        return [self._deserialize_schema_row(r) for r in rows]

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Get all schemas across all domains."""
        rows = self._conn.execute(
            "SELECT * FROM schemas ORDER BY formation_count DESC"
        ).fetchall()
        return [self._deserialize_schema_row(r) for r in rows]

    def count_schemas(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as c FROM schemas").fetchone()
        return row["c"] if row else 0

    def delete_schema(self, schema_id: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM schemas WHERE schema_id = ?", (schema_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _deserialize_schema_row(row: sqlite3.Row) -> dict[str, Any]:
        """Deserialize JSON fields in a schema row."""
        d = dict(row)
        for field in ("entity_signature", "tag_signature", "relationship_types"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    d[field] = {} if "signature" in field else []
        return d
