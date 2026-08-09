"""Memory-metadata mutator mixin for PgMemoryStore.

Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1
cap) — the single-row UPDATE writers that mutate a memory's non-heat
metadata (importance, access stats, value, extinction, protection,
staleness, provenance, compression, mood) share one concern: simple
targeted column writes with no cross-row coordination.
"""

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
        """Persist a memory's learned RL value (B2). Defensive on stores whose
        `value` column predates this migration — a failed UPDATE is swallowed so
        rating/credit never breaks on an un-migrated store.

        The pre-migration case is now rare (the migration is current-schema
        baseline); an UPDATE failing today is more likely a real regression
        than a stale column, so the first such failure is logged rather than
        silently absorbed forever (see silent_failure module docstring)."""
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

        Writes ONLY the ``extinction_strength`` scalar in [0,1]; the memory's
        content and heat_base are left untouched — extinction suppresses the
        effective retrieval weight without erasing the trace, so decaying
        (spontaneous recovery) or clearing (reinstatement) the tag restores the
        original association (Bouton 2004). Defensive on stores whose
        ``extinction_strength`` column predates this migration — a failed UPDATE
        is swallowed so deprecation never breaks on an un-migrated store.

        See ``update_memory_value`` docstring: the same rare-pre-migration
        reasoning applies, so the first failure is logged, not just swallowed."""
        try:
            e = max(0.0, min(1.0, float(extinction_strength)))
            self._execute(
                "UPDATE memories SET extinction_strength = %s WHERE id = %s",
                (e, memory_id),
            )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("pg_store.update_memory_extinction")
            silent_failure.note("pg_store.update_memory_extinction", exc)

    # ── User mood (Bower 1981 mood-congruent recall) ──────────────────
    # The pg_recall._get_user_mood(store) bridge duck-types against
    # ``get_user_mood()`` and consumes a scalar valence in [-1, +1].
    # We expose:
    #   - get_user_mood()       → scalar float (the bridge contract)
    #   - get_user_mood_state() → {valence, arousal} dict (richer reads)
    #   - set_user_mood(v, a)   → upsert (writers / emotion classifier)
    # Returns ``None`` from get_user_mood() iff the row is genuinely
    # absent — defensive; the schema seeds a 'default' neutral row, but
    # an in-flight migration or a manually deleted row should still
    # no-op the rerank rather than crash.
    # Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).

    def get_user_mood(self, user_id: str = "default") -> float | None:
        """Return the user's current mood valence in [-1, +1], or None.

        Scalar contract matches ``mcp_server/core/pg_recall.py:_get_user_mood``
        which clamps and floats the returned value. None means "no signal" —
        the MOOD_CONGRUENT_RERANK stage no-ops in that case (Bower 1981
        requires a real mood; we never fabricate one).
        """
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

        Refreshes ``updated_at`` automatically. Idempotent — repeated
        writes with the same value still bump the timestamp, which is
        the correct semantics for a "freshness of last observed mood"
        signal that downstream EMA aggregators may consult.
        """
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

        Written every forgetting cycle (including leak-down when interference
        abates), so the accumulator carries sustained-pressure history across
        cycles — the faithful discretization of gradual Rac1 erosion.
        source: mcp_server/core/active_forgetting.py (update_pressure_accum).
        """
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
