"""Memory-metadata mutator mixin for PgMemoryStore.

source: ADR-0554"""

from __future__ import annotations

from mcp_server.infrastructure.pg_store_host import PgStoreHost
from mcp_server.observability import silent_failure


class PgMemoryMetaMixin(PgStoreHost):
    """Single-row memory metadata writers + user-mood state."""

    def update_memory_importance(self, memory_id: int, importance: float) -> None:
        self._execute(
            "UPDATE memories SET importance = %s WHERE id = %s",
            (importance, memory_id),
        )
        self._conn.commit()

    def update_memory_access(self, memory_id: int) -> None:
        self._execute(
            "UPDATE memories SET last_accessed = NOW(), "
            "access_count = access_count + 1 WHERE id = %s",
            (memory_id,),
        )
        self._conn.commit()

    def update_memory_metamemory(
        self, memory_id: int, access_count: int, useful_count: int, confidence: float
    ) -> None:
        self._execute(
            "UPDATE memories SET access_count = %s, useful_count = %s, "
            "confidence = %s WHERE id = %s",
            (access_count, useful_count, confidence, memory_id),
        )
        self._conn.commit()

    def update_memory_value(self, memory_id: int, value: float) -> None:
        """Persist a memory's learned RL value.

        source: ADR-0554"""
        try:
            self._execute(
                "UPDATE memories SET value = %s WHERE id = %s",
                (value, memory_id),
            )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("pg_store.update_memory_value")
            silent_failure.note("pg_store.update_memory_value", exc)

    def update_memory_extinction(
        self, memory_id: int, extinction_strength: float
    ) -> None:
        """Persist a memory's reversible inhibitory extinction tag (E2).

        source: ADR-0554"""
        try:
            e = max(0.0, min(1.0, float(extinction_strength)))
            self._execute(
                "UPDATE memories SET extinction_strength = %s WHERE id = %s",
                (e, memory_id),
            )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("pg_store.update_memory_extinction")
            silent_failure.note("pg_store.update_memory_extinction", exc)

    # source: ADR-0554

    def get_user_mood(self, user_id: str = "default") -> float | None:
        """Return the user's current mood valence in [-1, +1], or None.

        source: ADR-0554"""
        row = self._execute(
            "SELECT valence FROM user_mood WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return float(row["valence"])
        except (KeyError, TypeError, ValueError):
            return None

    def get_user_mood_state(self, user_id: str = "default") -> dict[str, float] | None:
        """Return the full mood state ``{valence, arousal}`` or None.

        Reserved for future stages that consume arousal (Russell 1980
        circumplex). The MOOD_CONGRUENT_RERANK stage uses only valence
        and reads it via ``get_user_mood()``.
        """
        row = self._execute(
            "SELECT valence, arousal FROM user_mood WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return {
                "valence": float(row["valence"]),
                "arousal": float(row["arousal"]),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def set_user_mood(
        self,
        valence: float,
        arousal: float = 0.0,
        user_id: str = "default",
    ) -> None:
        """Upsert the user's mood state. Clamps both dims to [-1, +1].

        source: ADR-0554"""
        v = max(-1.0, min(1.0, float(valence)))
        a = max(-1.0, min(1.0, float(arousal)))
        self._execute(
            "INSERT INTO user_mood (user_id, valence, arousal, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (user_id) DO UPDATE "
            "SET valence = EXCLUDED.valence, "
            "    arousal = EXCLUDED.arousal, "
            "    updated_at = NOW()",
            (user_id, v, a),
        )
        self._conn.commit()

    def delete_memory(self, memory_id: int) -> bool:
        cur = self._execute("DELETE FROM memories WHERE id = %s", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def set_memory_protected(self, memory_id: int, protected: bool = True) -> None:
        self._execute(
            "UPDATE memories SET is_protected = %s WHERE id = %s",
            (protected, memory_id),
        )
        self._conn.commit()

    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None:
        self._execute(
            "UPDATE memories SET is_stale = %s WHERE id = %s", (stale, memory_id)
        )
        self._conn.commit()

    def set_source_attribution(self, memory_id: int, attribution: str) -> None:
        """Persist a provenance grade (I6-D6). Sole intended writer:
        handlers/validate_memory.py — see core/provenance.py for the
        verified/verifiable/unverifiable vocabulary this column now holds."""
        self._execute(
            "UPDATE memories SET source_attribution = %s WHERE id = %s",
            (attribution, memory_id),
        )
        self._conn.commit()

    def update_forgetting_pressure_accum(self, memory_id: int, accum: float) -> None:
        """Persist the permanent-circuit leaky-integrator state for one memory.

        source: ADR-0554"""
        self._execute(
            "UPDATE memories SET forgetting_pressure_accum = %s WHERE id = %s",
            (accum, memory_id),
        )
        self._conn.commit()

    # ── Compression ───────────────────────────────────────────────────

    def update_memory_compression(
        self,
        memory_id: int,
        content: str,
        embedding: bytes | None,
        compression_level: int,
        original_content: str | None = None,
    ) -> None:
        emb = self._bytes_to_vector(embedding)
        if original_content is not None:
            self._execute(
                "UPDATE memories SET content = %s, embedding = %s, "
                "compression_level = %s, compressed = TRUE, original_content = %s "
                "WHERE id = %s",
                (content, emb, compression_level, original_content, memory_id),
            )
        else:
            self._execute(
                "UPDATE memories SET content = %s, embedding = %s, "
                "compression_level = %s, compressed = TRUE "
                "WHERE id = %s",
                (content, emb, compression_level, memory_id),
            )
        self._conn.commit()
