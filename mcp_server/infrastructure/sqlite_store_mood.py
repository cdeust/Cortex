"""User mood and memory supersession mixin for SqliteMemoryStore.

Implements methods that exist in PgMemoryStore but had no SQLite
equivalent, causing silent no-ops under the advertised fallback backend:

    get_user_mood(user_id) -> float | None
    get_user_mood_state(user_id) -> dict | None
    set_user_mood(valence, arousal, user_id) -> None
    get_embeddings_for_memories(memory_ids) -> dict[int, bytes]

source: ADR-0611"""

from __future__ import annotations

import sqlite3

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection


class SqliteMoodMixin:
    """Mood state, memory supersession, and bulk-embedding methods on SQLite.

    source: ADR-0611"""

    _conn: PsycopgCompatConnection
    _has_vec: bool

    # source: ADR-0611

    def get_user_mood(self, user_id: str = "default") -> float | None:
        """Return the user's current mood valence in [-1, +1], or None.

                Precondition: user_id is a non-empty string.
                Postcondition: returns a float in [-1, +1] if a row exists for
                  user_id, else None (semantics: "no signal — do not rerank").

        source: ADR-0611"""
        try:
            row = self._conn.execute(
                "SELECT valence FROM user_mood WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        except sqlite3.Error:
            # user_mood table absent (pre-migration DB) — safe no-op.
            return None
        if row is None:
            return None
        try:
            val = row["valence"]
            return float(val)
        except (KeyError, TypeError, ValueError, IndexError):
            return None

    def get_user_mood_state(self, user_id: str = "default") -> dict[str, float] | None:
        """Return the full mood state ``{valence, arousal}`` or None.

                Precondition: user_id is a non-empty string.
                Postcondition: returns dict with keys 'valence' and 'arousal', both
                  floats in [-1, +1], or None if no row exists.

        source: ADR-0611"""
        try:
            row = self._conn.execute(
                "SELECT valence, arousal FROM user_mood WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            valence, arousal = row["valence"], row["arousal"]
            return {"valence": float(valence), "arousal": float(arousal)}
        except (KeyError, TypeError, ValueError, IndexError):
            return None

    def set_user_mood(
        self,
        valence: float,
        arousal: float = 0.0,
        user_id: str = "default",
    ) -> None:
        """Upsert the user's mood state. Clamps both dims to [-1, +1].

                Precondition: valence, arousal are numeric; user_id is a non-empty
                  string.
                Postcondition: a row for user_id exists in user_mood with the clamped
                  valence and arousal; updated_at is refreshed.

        source: ADR-0611"""
        v = max(-1.0, min(1.0, float(valence)))
        a = max(-1.0, min(1.0, float(arousal)))
        try:
            self._conn.execute(
                "INSERT INTO user_mood (user_id, valence, arousal, updated_at) "
                "VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
                "ON CONFLICT(user_id) DO UPDATE "
                "SET valence = excluded.valence, "
                "    arousal = excluded.arousal, "
                "    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (user_id, v, a),
            )
            self._conn.commit()
        except sqlite3.Error:
            # user_mood table absent (pre-migration DB) — safe no-op.
            pass

    # ── Bulk embedding fetch ──────────────────────────────────────────

    def get_embeddings_for_memories(self, memory_ids: list[int]) -> dict[int, bytes]:
        """Bulk fetch embeddings for a known set of memory IDs.

                Precondition: memory_ids is a list of valid integer IDs (may be empty).
                Postcondition: returns a dict mapping memory_id -> embedding_bytes for
                  every ID that has a non-NULL embedding in memories_vec; IDs with no
                  embedding are absent from the dict (not None values).

        source: ADR-0611"""
        if not memory_ids or not self._has_vec:
            return {}
        result: dict[int, bytes] = {}
        for mid in memory_ids:
            try:
                row = self._conn.execute(
                    "SELECT embedding FROM memories_vec WHERE rowid = ?",
                    (int(mid),),
                ).fetchone()
                if row is None:
                    continue
                raw = row["embedding"]
                if raw is not None:
                    result[int(mid)] = bytes(raw)
            except sqlite3.Error:
                continue
        return result
