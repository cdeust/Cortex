"""The legacy backfill runs exactly once, on the upgrade that creates the
column (issue #368).

Why this is tested against a real pre-migration database rather than by
asserting substrings of the DDL: the property that matters is temporal — rows
present when the column is created become 'legacy', rows written afterwards
keep the 'unknown' DEFAULT and are demoted at read time. A text assertion on
the migration source cannot distinguish those two cases, and it is exactly
the distinction the whole design rests on.

SQLite's ALTER TABLE ... DROP COLUMN (3.35+) lets the test reconstruct the
pre-#365 shape from a current schema, so the upgrade path is exercised for
real instead of simulated.
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_server.core.capture_origin import (
    ORIGIN_DELIBERATE,
    ORIGIN_LEGACY,
    ORIGIN_NETWORK,
    ORIGIN_UNKNOWN,
    may_bypass_write_gate_on_content,
    trust_factor,
)
from mcp_server.infrastructure.sqlite_schema import COLUMN_BACKFILLS
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_DIM = 384
# Any value strictly inside (0, 1) exercises the demotion branch. The MEASURED
# value of W is not this test's business — it comes from the committed ablation
# sweep, and hard-coding the real one here would silently pin the algorithm to
# a test literal.
_W = 0.5


def _emb(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(_DIM).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tobytes()


def _insert(store: SqliteMemoryStore, content: str, origin: str | None) -> int:
    payload = {
        "content": content,
        "embedding": _emb(abs(hash(content)) % 1000),
        "source": "test",
        "domain": "legacy-backfill-test",
        "heat": 0.5,
    }
    if origin is not None:
        payload["capture_origin"] = origin
    return store.insert_memory(payload)


def _origin_of(store: SqliteMemoryStore, content: str) -> str:
    row = store._conn.execute(
        "SELECT capture_origin FROM memories WHERE content = ?", (content,)
    ).fetchone()
    assert row is not None, f"memory not found: {content}"
    return row["capture_origin"]


class TestTrustFactorVocabulary:
    """The pure read-side policy, independent of any storage."""

    @pytest.mark.parametrize(
        "origin", [ORIGIN_DELIBERATE, "local_action", ORIGIN_LEGACY]
    )
    def test_trusted_origins_keep_full_weight(self, origin: str):
        assert trust_factor(origin, _W) == 1.0

    @pytest.mark.parametrize("origin", [ORIGIN_NETWORK, ORIGIN_UNKNOWN])
    def test_untrusted_origins_are_demoted(self, origin: str):
        assert trust_factor(origin, _W) == _W

    def test_unrecognised_origin_is_demoted(self):
        """Fail-closed: a value this module has never seen is not trusted.

        The read side mirrors the write side's allowlist. Under a denylist a
        newly added off-machine tool would classify as something unlisted and
        silently keep full ranking weight — the control would stop applying
        with no failing test.
        """
        assert trust_factor("some_channel_nobody_classified", _W) == _W

    def test_legacy_never_earns_the_write_gate_bypass(self):
        """`legacy` is trusted for RANKING only, never for admission.

        It is written solely by the migration, so no live write path can
        claim it — but the allowlist is asserted rather than assumed, since
        adding it there would let a forged origin skip the novelty gate.
        """
        assert may_bypass_write_gate_on_content(ORIGIN_LEGACY) is False


class TestLegacyBackfillOnUpgrade:
    """The upgrade path, exercised against a real pre-#365 database."""

    def test_rows_predating_the_column_become_legacy(self):
        store = SqliteMemoryStore()
        try:
            _insert(store, "written before the attribute existed", ORIGIN_NETWORK)
            _insert(store, "also written before", ORIGIN_DELIBERATE)

            # Reconstruct the pre-#365 shape: the column simply did not exist.
            store._conn.execute("ALTER TABLE memories DROP COLUMN capture_origin")
            store._conn.commit()

            store._run_migrations()
            store._conn.commit()

            assert _origin_of(store, "written before the attribute existed") == (
                ORIGIN_LEGACY
            )
            assert _origin_of(store, "also written before") == ORIGIN_LEGACY
        finally:
            store.close()

    def test_rows_written_after_the_upgrade_stay_unknown(self):
        """The other side of the frontier — the one that must be demoted.

        Without this assertion the backfill could be written as a blanket
        UPDATE outside the creation branch, which would keep re-marking
        genuinely unclassified rows as trusted forever.
        """
        store = SqliteMemoryStore()
        try:
            store._conn.execute("ALTER TABLE memories DROP COLUMN capture_origin")
            store._conn.commit()
            store._run_migrations()
            store._conn.commit()

            _insert(store, "written after the upgrade, no attribution", None)
            assert _origin_of(store, "written after the upgrade, no attribution") == (
                ORIGIN_UNKNOWN
            )
            assert trust_factor(ORIGIN_UNKNOWN, _W) == _W
        finally:
            store.close()

    def test_backfill_does_not_rerun_on_an_existing_column(self):
        """Idempotence in the direction that matters.

        A second migration pass must not overwrite values the write path has
        recorded since the upgrade — the failure mode that would quietly
        promote every unclassified row to trusted.
        """
        store = SqliteMemoryStore()
        try:
            _insert(store, "network memory that must stay network", ORIGIN_NETWORK)
            store._run_migrations()
            store._conn.commit()
            assert _origin_of(store, "network memory that must stay network") == (
                ORIGIN_NETWORK
            )
        finally:
            store.close()


class TestBackfillDeclaration:
    def test_capture_origin_has_a_backfill_entry(self):
        assert ("memories", "capture_origin") in COLUMN_BACKFILLS
        assert "legacy" in COLUMN_BACKFILLS[("memories", "capture_origin")]


class TestPostgresBackfillIsInsideTheCreationBranch:
    """PG parity, asserted structurally rather than behaviourally.

    Honest statement of what this does and does not prove: the SQLite tests
    above exercise the real upgrade path, because a throwaway in-memory
    database can be dropped back to its pre-#365 shape at no cost. Doing the
    same to PostgreSQL means dropping a column from the shared `cortex_test`
    database, which the autouse isolation fixture (row-level DELETEs, not
    schema recreation) would not repair for the tests that follow.

    So this asserts the one property that would silently break the PG
    upgrade: the UPDATE must sit INSIDE the `IF NOT EXISTS` branch. Outside
    it, the statement would re-run on every startup and relabel genuinely
    unclassified rows as trusted — turning a fail-closed control into a
    fail-open one.
    """

    def test_update_sits_between_add_column_and_end_if(self):
        from mcp_server.infrastructure.pg_schema import MIGRATIONS_DDL

        anchor = MIGRATIONS_DDL.index("ADD COLUMN capture_origin")
        backfill = MIGRATIONS_DDL.index(
            "UPDATE memories SET capture_origin = 'legacy'", anchor
        )
        end_if = MIGRATIONS_DDL.index("END IF;", anchor)

        assert anchor < backfill < end_if, (
            "the legacy backfill escaped the IF NOT EXISTS branch — it would "
            "re-run on every startup and promote unclassified rows to trusted"
        )
