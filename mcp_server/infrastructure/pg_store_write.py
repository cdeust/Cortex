"""Memory INSERT-path mixin for PgMemoryStore.

source: ADR-0583"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import DictRow

from mcp_server.infrastructure.pg_store_host import PgStoreHost
from mcp_server.infrastructure.pg_store_serialize import _now_iso
from mcp_server.shared.temporal_normalize import normalize_date_to_iso


class PgWriteMixin(PgStoreHost):
    """Memory INSERT on PostgreSQL — SQL constant, param building, commit."""

    # source: ADR-0583
    _INSERT_MEMORY_SQL = """INSERT INTO memories (
                content, embedding, tags, source, domain,
                directory_context, created_at, last_accessed, heat_base_set_at,
                heat_base, surprise_score, importance,
                emotional_valence, confidence, store_type,
                is_protected, consolidation_stage,
                theta_phase_at_encoding, encoding_strength,
                separation_index, interference_score,
                schema_match_score, schema_id,
                hippocampal_dependency, is_benchmark, agent_context,
                is_global, stage_entered_at,
                arousal, dominant_emotion, supersedes_id,
                source_attribution, stimulus_signature, extinction_strength,
                write_class, capture_origin
            ) VALUES (
                %(content)s, %(embedding)s, %(tags)s::jsonb, %(source)s, %(domain)s,
                %(directory_context)s, %(created_at)s, %(last_accessed)s,
                %(heat_base_set_at)s,
                %(heat)s, %(surprise_score)s, %(importance)s,
                %(emotional_valence)s, %(confidence)s, %(store_type)s,
                %(is_protected)s, %(consolidation_stage)s,
                %(theta_phase)s, %(encoding_strength)s,
                %(separation_index)s, %(interference_score)s,
                %(schema_match_score)s, %(schema_id)s,
                %(hippocampal_dependency)s, %(is_benchmark)s, %(agent_context)s,
                %(is_global)s, %(stage_entered_at)s,
                %(arousal)s, %(dominant_emotion)s, %(supersedes_id)s,
                %(source_attribution)s, %(stimulus_signature)s, %(extinction_strength)s,
                %(write_class)s, %(capture_origin)s
            ) RETURNING id"""

    def _resolve_insert_dates(self, data: dict[str, Any], now: str) -> tuple[str, str]:
        """Normalize created_at and anchor heat_base_set_at to the event date.

                Returns ``(created_at, heat_base_set_at)`` — both already defaulted.

        source: ADR-0583"""
        raw_created = data.get("created_at")
        if raw_created and isinstance(raw_created, str):
            raw_created = normalize_date_to_iso(raw_created) or raw_created
        created_at = raw_created or now
        heat_base_anchor = data.get("heat_base_set_at") or created_at
        return created_at, heat_base_anchor

    def _insert_identity_fields(
        self, data: dict[str, Any], now: str, created_at: str, heat_base_anchor: str
    ) -> dict[str, Any]:
        """Content/embedding/tags/timestamp/heat/protection half of the
        _INSERT_MEMORY_SQL bind parameters. See ``_insert_signal_fields``
        for the remaining (schema/interference/provenance) half."""
        embedding = self._bytes_to_vector(data.get("embedding"))
        return {
            "content": data["content"],
            "embedding": embedding,
            "tags": json.dumps(data.get("tags", [])),
            "source": data.get("source", ""),
            "domain": data.get("domain", ""),
            "directory_context": data.get("directory_context", ""),
            "created_at": created_at,
            "last_accessed": now,
            "heat_base_set_at": heat_base_anchor,
            "heat": data.get("heat", 1.0),
            "surprise_score": data.get("surprise_score", 0.0),
            "importance": data.get("importance", 0.5),
            "emotional_valence": data.get("emotional_valence", 0.0),
            "confidence": data.get("confidence", 1.0),
            "store_type": data.get("store_type", "episodic"),
            "is_protected": data.get("is_protected", False),
            "consolidation_stage": data.get("consolidation_stage", "labile"),
            "theta_phase": data.get("theta_phase_at_encoding", 0.0),
            "encoding_strength": data.get("encoding_strength", 1.0),
        }

    def _insert_signal_fields(
        self, data: dict[str, Any], created_at: str
    ) -> dict[str, Any]:
        """Schema/interference/provenance half of the _INSERT_MEMORY_SQL
        bind parameters. See ``_insert_identity_fields`` for the rest."""
        return {
            "separation_index": data.get("separation_index", 0.0),
            "interference_score": data.get("interference_score", 0.0),
            "schema_match_score": data.get("schema_match_score", 0.0),
            "schema_id": data.get("schema_id"),
            "hippocampal_dependency": data.get("hippocampal_dependency", 1.0),
            "is_benchmark": data.get("is_benchmark", False),
            "agent_context": data.get("agent_context", ""),
            "is_global": data.get("is_global", False),
            "stage_entered_at": data.get("stage_entered_at") or created_at,
            "arousal": data.get("arousal", 0.0),
            "dominant_emotion": data.get("dominant_emotion", "neutral"),
            "supersedes_id": data.get("supersedes_id"),
            "source_attribution": data.get("source_attribution", "unknown"),
            # source: ADR-0583
            "capture_origin": data.get("capture_origin", "unknown"),
            "stimulus_signature": data.get("stimulus_signature", ""),
            "extinction_strength": data.get("extinction_strength", 0.0),
            # source: ADR-0583
            "write_class": data.get("write_class") or "deliberate",
        }

    def _build_insert_params(self, data: dict[str, Any]) -> dict[str, Any]:
        """Map a memory record to the _INSERT_MEMORY_SQL bind parameters.

        Delegates date resolution to ``_resolve_insert_dates`` (A3 decay
        clock) and the field set to ``_insert_identity_fields`` /
        ``_insert_signal_fields`` — split three ways to stay under the
        project's 40-line-per-method cap; the returned dict is the same
        33-key mapping either way.
        """
        now = _now_iso()
        created_at, heat_base_anchor = self._resolve_insert_dates(data, now)
        params = self._insert_identity_fields(data, now, created_at, heat_base_anchor)
        params.update(self._insert_signal_fields(data, created_at))
        return params

    def _insert_memory_on(
        self, conn: psycopg.Connection[DictRow], data: dict[str, Any]
    ) -> int:
        """Run the memory INSERT on ``conn`` WITHOUT committing.

        source: ADR-0583"""
        row = conn.execute(
            self._INSERT_MEMORY_SQL, self._build_insert_params(data)
        ).fetchone()
        if row is None:
            raise RuntimeError("INSERT ... RETURNING id produced no row")
        return int(row["id"])

    def insert_memory(self, data: dict[str, Any]) -> int:
        """Insert a memory and return its ID."""
        row = self._execute(
            self._INSERT_MEMORY_SQL, self._build_insert_params(data)
        ).fetchone()
        self._conn.commit()
        if row is None:
            raise RuntimeError("INSERT ... RETURNING id produced no row")
        return int(row["id"])
