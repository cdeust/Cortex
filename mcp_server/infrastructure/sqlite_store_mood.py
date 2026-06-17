"""User mood and memory supersession mixin for SqliteMemoryStore.

Implements the five methods that exist in PgMemoryStore but had no SQLite
equivalent, causing silent no-ops under the advertised fallback backend:

    get_user_mood(user_id) -> float | None
    get_user_mood_state(user_id) -> dict | None
    set_user_mood(valence, arousal, user_id) -> None
    set_superseded_by(old_id, new_id) -> None
    get_embeddings_for_memories(memory_ids) -> dict[int, bytes]

All signatures mirror PgMemoryStore exactly (duck-type compatibility).
"""

from __future__ import annotations

import sqlite3


class SqliteMoodMixin:
    """Mood state, memory supersession, and bulk-embedding methods on SQLite.

    Source references are on each method below.
    """

    _conn: sqlite3.Connection
    _has_vec: bool

    # ── User mood (Bower 1981 mood-congruent recall) ──────────────────
    # Mirrors PgMemoryStore: pg_recall._get_user_mood() duck-types against
    # get_user_mood() and consumes a scalar valence in [-1, +1].
    # Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).

    def get_user_mood(self, user_id: str = "default") -> float | None:
        """Return the user's current mood valence in [-1, +1], or None.

        Precondition: user_id is a non-empty string.
        Postcondition: returns a float in [-1, +1] if a row exists for
          user_id, else None (semantics: "no signal — do not rerank").

        Mirrors PgMemoryStore.get_user_mood. None means the mood
        MOOD_CONGRUENT_RERANK stage should no-op (Bower 1981 requires a
        real mood; we never fabricate one).
        Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
        """
        try:
            row = self._conn.execute(
                "SELECT valence FROM user_mood WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        except Exception:
            # user_mood table absent (pre-migration DB) — safe no-op.
            return None
        if row is None:
            return None
        try:
            val = row["valence"] if hasattr(row, "__getitem__") else row[0]
            return float(val)
        except (KeyError, TypeError, ValueError, IndexError):
            return None

    def get_user_mood_state(self, user_id: str = "default") -> dict[str, float] | None:
        """Return the full mood state ``{valence, arousal}`` or None.

        Precondition: user_id is a non-empty string.
        Postcondition: returns dict with keys 'valence' and 'arousal', both
          floats in [-1, +1], or None if no row exists.

        Mirrors PgMemoryStore.get_user_mood_state. Reserved for future
        stages that consume arousal (Russell 1980 circumplex). The
        MOOD_CONGRUENT_RERANK stage only uses valence via get_user_mood().
        Source: Russell, J.A. (1980). "A circumplex model of affect."
          J. Personality & Social Psychology 39(6), 1161-1178.
        """
        try:
            row = self._conn.execute(
                "SELECT valence, arousal FROM user_mood WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        try:
            if hasattr(row, "__getitem__"):
                valence, arousal = row["valence"], row["arousal"]
            else:
                valence, arousal = row[0], row[1]
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

        Idempotent — repeated writes with the same value bump updated_at,
        which is the correct semantics for a "freshness of last observed
        mood" signal.
        Mirrors PgMemoryStore.set_user_mood.
        Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
        """
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
        except Exception:
            # user_mood table absent (pre-migration DB) — safe no-op.
            pass

    # ── Memory supersession ───────────────────────────────────────────

    def set_superseded_by(self, old_id: int, new_id: int) -> None:
        """Mark ``old_id`` as superseded by ``new_id`` (back-pointer edge).

        Precondition: old_id and new_id are valid memory IDs.
        Postcondition: memories.superseded_by_id = new_id for the row with
          id = old_id; the forward edge (new.supersedes_id = old) is written
          by insert_memory when data["supersedes_id"] is supplied.

        Idempotent — re-running with the same args is a no-op overwrite.
        Mirrors PgMemoryStore.set_superseded_by.
        """
        try:
            self._conn.execute(
                "UPDATE memories SET superseded_by_id = ? WHERE id = ?",
                (new_id, old_id),
            )
            self._conn.commit()
        except Exception:
            # superseded_by_id column absent (pre-migration DB) — safe no-op.
            pass

    # ── Bulk embedding fetch ──────────────────────────────────────────

    def get_embeddings_for_memories(self, memory_ids: list[int]) -> dict[int, bytes]:
        """Bulk fetch embeddings for a known set of memory IDs.

        Precondition: memory_ids is a list of valid integer IDs (may be empty).
        Postcondition: returns a dict mapping memory_id -> embedding_bytes for
          every ID that has a non-NULL embedding in memories_vec; IDs with no
          embedding are absent from the dict (not None values).

        Mirrors PgMemoryStore.get_embeddings_for_memories.
        Used by recall_pipeline.hopfield_complete to avoid per-ID round trips.

        SQLite note: memories_vec is the sqlite-vec virtual table. When
        _has_vec is False the table does not exist and we return an empty
        dict (matching PG returning zero rows for embeddings that are NULL).
        We fetch one row at a time because sqlite-vec does not support WHERE
        rowid IN (...) batch queries in the versions available at fallback
        scale; the loop is bounded by len(memory_ids) which is capped by the
        recall pool size (typically <= 300).
        Engineering choice: individual rowid lookups are O(1) in sqlite-vec
        B-tree index — the loop is therefore O(N) with a small constant.
        """
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
                raw = row["embedding"] if hasattr(row, "__getitem__") else row[0]
                if raw is not None:
                    result[int(mid)] = bytes(raw)
            except Exception:
                continue
        return result
