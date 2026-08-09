"""Cortical-schema (Piaget accommodation, Tse 2007) mixin for PgMemoryStore.

Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — named ``cortical_schema`` (not ``schema``) to avoid
colliding with ``pg_store_ddl.py``'s unrelated database-DDL "schema"
vocabulary; this is the cognitive-science sense (schema_engine.py).
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgCorticalSchemaMixin(PgStoreHost):
    """Cortical knowledge-structure ("schema") CRUD on PostgreSQL."""

    def insert_schema(self, data: dict[str, Any]) -> int:
        try:
            row = self._execute(
                """INSERT INTO schemas (
                    schema_id, domain, label, entity_signature,
                    relationship_types, tag_signature,
                    consistency_threshold, formation_count,
                    assimilation_count, violation_count
                ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                          %s, %s, %s, %s) RETURNING id""",
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
                ),
            ).one()
            self._conn.commit()
            return row["id"]
        except psycopg.errors.UniqueViolation:
            self._conn.rollback()
            return self._update_existing_schema(data)

    def _update_existing_schema(self, data: dict[str, Any]) -> int:
        self._execute(
            """UPDATE schemas SET
                domain = %s, label = %s, entity_signature = %s::jsonb,
                relationship_types = %s::jsonb, tag_signature = %s::jsonb,
                consistency_threshold = %s, formation_count = %s,
                assimilation_count = %s, violation_count = %s,
                last_updated = NOW()
            WHERE schema_id = %s""",
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
                data["schema_id"],
            ),
        )
        self._conn.commit()
        row = self._execute(
            "SELECT id FROM schemas WHERE schema_id = %s",
            (data["schema_id"],),
        ).fetchone()
        return row["id"] if row else 0

    def get_schemas_for_domain(self, domain: str) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM schemas WHERE domain = %s ORDER BY formation_count DESC",
            (domain,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_schemas(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM schemas ORDER BY formation_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def count_schemas(self) -> int:
        row = self._execute("SELECT COUNT(*) AS c FROM schemas").fetchone()
        return row["c"] if row else 0

    def delete_schema(self, schema_id: str) -> bool:
        cur = self._execute("DELETE FROM schemas WHERE schema_id = %s", (schema_id,))
        self._conn.commit()
        return cur.rowcount > 0
