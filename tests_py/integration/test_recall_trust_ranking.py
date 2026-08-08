"""Trust/provenance ranking under adversarial retrieval poisoning (issue #368).

The property under test: a memory whose capture_origin is untrusted must not
outrank a trusted one that answers the same query, even when the untrusted
passage wins on pure similarity. Before the trust term exists these tests
fail — that failure IS the measurement of the attack, and it is why the
corpus declares its hostile entries with the higher similarity.

Skip pattern mirrors tests_py/integration/test_recall_e2e.py: import _USE_PG
from conftest and apply pytestmark, so the module skips cleanly when PG is
absent rather than erroring at collection.

Source: arXiv 2604.16548 (retrieve-phase corruption; "Retrieval-time
filtering alone is insufficient"). The assertions therefore read the ORDER
produced by the ranking function, never a post-hoc filtered list.
"""

from __future__ import annotations

import pytest

pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

from benchmarks.lib.adversarial_corpus import (  # noqa: E402
    AdversarialPair,
    all_pairs,
    memory_payloads,
)
from mcp_server.core.capture_origin import trusted_origins_at_read  # noqa: E402
from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: E402
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

# The canonical query direction is seeded (rng(0)) inside this helper. Import
# it rather than re-deriving it: two modules building "the query direction"
# from separate literals would drift apart silently, and every similarity in
# the corpus is expressed RELATIVE to that one direction.
from tests_py.integration.test_recall_e2e import _query_aligned_emb  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — trust ranking needs live schema"
)

_DOMAIN = "trust-ranking-test"

# A demotion strong enough to reorder the corpus, used to assert the MECHANISM.
# Not the production weight: that one is measured by the committed ablation
# sweep and lives with its source, not in a test file.
_TEST_UNTRUSTED_FACTOR = 0.2


@pytest.fixture
def store():
    """PgMemoryStore scoped to this module's domain; cleaned on teardown."""
    s = PgMemoryStore()
    yield s
    try:
        s._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
        s._conn.commit()
    finally:
        s.close()


def _seed_pair(store: PgMemoryStore, pair: AdversarialPair) -> None:
    """Insert both sides of `pair`, each at its declared similarity."""
    legitimate, adversarial = memory_payloads(pair, _DOMAIN)
    legitimate["embedding"] = _query_aligned_emb(pair.legitimate_similarity, seed=11)
    adversarial["embedding"] = _query_aligned_emb(pair.adversarial_similarity, seed=12)
    store.insert_memory(legitimate)
    store.insert_memory(adversarial)


def _ranked_contents(
    store: PgMemoryStore, query: str, *, untrusted_factor: float
) -> list[str]:
    """Recall `query` and return contents in ranked order (no client rerank).

    The trust policy is passed explicitly. `untrusted_factor` is a TEST
    value, deliberately not the production constant: pinning the measured W
    here would make these assertions re-fail every time the ablation is
    re-run, and would quietly turn a test literal into the algorithm's
    source of truth (§8).
    """
    rows = store.recall_memories(
        query_text=query,
        query_embedding=_query_aligned_emb(1.0),
        intent="general",
        domain=_DOMAIN,
        min_heat=0.0,
        max_results=10,
        weights={
            "vector": 1.0,
            "fts": 0.5,
            "ngram": 0.3,
            "heat": 0.3,
            "recency": 0.0,
        },
        trusted_origins=trusted_origins_at_read(),
        untrusted_factor=untrusted_factor,
    )
    return [r["content"] for r in rows]


def _rank_of(contents: list[str], needle: str) -> int:
    """Index of `needle` in `contents`; -1 when absent."""
    return contents.index(needle) if needle in contents else -1


class TestCorpusIsActuallyAdversarial:
    """Guards the corpus before anything is concluded from it."""

    @pytest.mark.parametrize("pair", all_pairs(), ids=lambda p: p.scenario)
    def test_adversarial_entry_wins_on_similarity(self, pair: AdversarialPair):
        """A hostile entry that loses on similarity would test nothing.

        This is the assumption every other test in this module rests on, so
        it is asserted rather than trusted: without it a green suite would be
        compatible with having no defence at all.
        """
        assert pair.adversarial_similarity > pair.legitimate_similarity


class TestUntrustedOriginIsDemoted:
    """The property #368 introduces: origin outranks raw similarity."""

    @pytest.mark.parametrize("pair", all_pairs(), ids=lambda p: p.scenario)
    def test_trusted_memory_outranks_untrusted_lookalike(
        self, store, pair: AdversarialPair
    ):
        """A `deliberate` memory must rank above a `network` one that wins
        on similarity.

        Fails before the trust term exists — that failure measures the
        attack. The assertion reads the ranking function's own order, not a
        filtered subset, because the survey's finding is that filtering after
        ranking is insufficient.
        """
        _seed_pair(store, pair)
        contents = _ranked_contents(
            store, pair.query, untrusted_factor=_TEST_UNTRUSTED_FACTOR
        )

        legit_rank = _rank_of(contents, pair.legitimate)
        hostile_rank = _rank_of(contents, pair.adversarial)

        assert legit_rank >= 0, (
            f"{pair.scenario}: legitimate memory was not retrieved at all "
            f"— the scenario cannot be evaluated"
        )
        assert hostile_rank >= 0, (
            f"{pair.scenario}: adversarial memory absent from results; it "
            f"must be RETRIEVED and DEMOTED, not filtered out — a filter "
            f"would not exercise the ranking property under test"
        )
        assert legit_rank < hostile_rank, (
            f"{pair.scenario}: untrusted (network) memory ranked "
            f"{hostile_rank} vs trusted (deliberate) {legit_rank}. "
            f"Attack: {pair.attack}"
        )


class TestDefaultsAreTheIdentityTransform:
    """An unaware caller must get the pre-#368 ranking, bit for bit."""

    def test_omitting_the_policy_leaves_the_hostile_entry_on_top(self, store):
        """Without the trust arguments, similarity wins again.

        This is what makes the new stored-procedure parameters safe to
        deploy ahead of the measured weight, and what the benchmark's
        before-arm relies on: if the defaults demoted anything, every
        paired measurement would compare two different rankings and the
        regression numbers would be meaningless.
        """
        pair = all_pairs()[0]
        _seed_pair(store, pair)

        rows = store.recall_memories(
            query_text=pair.query,
            query_embedding=_query_aligned_emb(1.0),
            intent="general",
            domain=_DOMAIN,
            min_heat=0.0,
            max_results=10,
            weights={
                "vector": 1.0,
                "fts": 0.5,
                "ngram": 0.3,
                "heat": 0.3,
                "recency": 0.0,
            },
        )
        contents = [r["content"] for r in rows]

        assert _rank_of(contents, pair.adversarial) < _rank_of(
            contents, pair.legitimate
        ), (
            "defaults are not the identity transform — the stored procedure "
            "demoted something without being asked to"
        )
