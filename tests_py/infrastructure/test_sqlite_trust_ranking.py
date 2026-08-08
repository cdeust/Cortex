"""Trust demotion on the SQLite backend (issue #368, §12.3 both-backends).

The PG counterpart lives in tests_py/integration/test_recall_trust_ranking.py
and exercises the `trust_weighted` CTE. This module asserts the same property
against the client-side fusion in sqlite_store_search.py, because the two
backends do not share an implementation: PG fuses server-side in PL/pgSQL,
SQLite fuses in Python, and until #368 SQLite had no multiplicative
post-fusion chain at all. A property proven on one says nothing about the
other.

The corpus is shared with the PG tests and with the ablation, so all three
argue about the same passages.
"""

from __future__ import annotations

import numpy as np
import pytest

from benchmarks.lib.adversarial_corpus import (
    AdversarialPair,
    all_pairs,
    memory_payloads,
)
from mcp_server.core.capture_origin import trusted_origins_at_read
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_DIM = 384
_DOMAIN = "sqlite-trust-ranking-test"

# Test value, not the production weight — see the PG module's note: pinning
# the measured W in a test would make it the algorithm's source of truth.
_TEST_UNTRUSTED_FACTOR = 0.2


def _aligned(similarity: float, seed: int) -> bytes:
    """384-dim unit vector at `similarity` cosine to the query direction.

    Same construction as the PG suite (Gram-Schmidt against a seed-0 base),
    restated here rather than imported: that helper is bound to the PG test
    module, which skips wholesale when psycopg is absent — importing it would
    make this SQLite-only suite skip for a reason that does not apply to it.
    """
    rng0 = np.random.default_rng(0)
    base = rng0.standard_normal(_DIM).astype(np.float32)
    base /= np.linalg.norm(base)
    if similarity >= 1.0:
        return base.tobytes()
    rng = np.random.default_rng(seed)
    other = rng.standard_normal(_DIM).astype(np.float32)
    other -= other.dot(base) * base
    other /= np.linalg.norm(other)
    mixed = similarity * base + np.sqrt(max(0.0, 1.0 - similarity**2)) * other
    return mixed.astype(np.float32).tobytes()


@pytest.fixture
def store():
    s = SqliteMemoryStore()
    yield s
    s.close()


def _seed(store: SqliteMemoryStore, pair: AdversarialPair) -> None:
    legitimate, adversarial = memory_payloads(pair, _DOMAIN)
    legitimate["embedding"] = _aligned(pair.legitimate_similarity, 11)
    adversarial["embedding"] = _aligned(pair.adversarial_similarity, 12)
    store.insert_memory(legitimate)
    store.insert_memory(adversarial)


def _ranked(store: SqliteMemoryStore, pair: AdversarialPair, factor: float):
    rows = store.recall_memories(
        query_text=pair.query,
        query_embedding=_aligned(1.0, 0),
        intent="general",
        domain=_DOMAIN,
        min_heat=0.0,
        max_results=10,
        trusted_origins=trusted_origins_at_read(),
        untrusted_factor=factor,
    )
    return [r["content"] for r in rows]


class TestSqliteTrustDemotion:
    @pytest.mark.parametrize("pair", all_pairs(), ids=lambda p: p.scenario)
    def test_trusted_outranks_untrusted_lookalike(self, store, pair: AdversarialPair):
        _seed(store, pair)
        contents = _ranked(store, pair, _TEST_UNTRUSTED_FACTOR)

        assert pair.legitimate in contents, (
            f"{pair.scenario}: legitimate memory not retrieved — scenario "
            f"cannot be evaluated"
        )
        assert pair.adversarial in contents, (
            f"{pair.scenario}: adversarial memory absent; it must be "
            f"RETRIEVED and DEMOTED, not filtered out"
        )
        assert contents.index(pair.legitimate) < contents.index(pair.adversarial), (
            f"{pair.scenario}: untrusted memory outranked the trusted one on "
            f"the SQLite backend. Attack: {pair.attack}"
        )

    def test_default_factor_is_the_identity_transform(self, store):
        """Omitting the policy must leave the pre-#368 order intact."""
        pair = all_pairs()[0]
        _seed(store, pair)
        rows = store.recall_memories(
            query_text=pair.query,
            query_embedding=_aligned(1.0, 0),
            intent="general",
            domain=_DOMAIN,
            min_heat=0.0,
            max_results=10,
        )
        contents = [r["content"] for r in rows]
        assert contents.index(pair.adversarial) < contents.index(pair.legitimate), (
            "SQLite defaults are not the identity transform"
        )
