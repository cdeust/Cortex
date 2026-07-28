"""Live-PG tests for spread_activation_memories (ADR-0054).

Two coupled defects, fixed together and tested together per the ADR's
"never one without the other" decision:

1. The stored procedure declared a plain ``WITH`` for its self-referencing
   ``spread`` CTE instead of ``WITH RECURSIVE`` -- every single call raised
   ``relation "spread" does not exist``, silently swallowed by
   ``recall_pipeline.spreading_activation_expand``'s bare
   ``except Exception``. The channel has been 100% dead in production
   since its introduction (8228a0d2). Test (a) below is the integration
   test that would have caught this on day one -- the existing test suite
   only ever exercised a Python-side ``_FakeStore`` double
   (tests_py/core/test_pg_recall_pipeline.py), never the real PL/pgSQL
   function.
2. Once fixed, the function had no domain filter: the entity graph is
   shared by design (see pg_schema.py module comment), but the final
   entity->memory mapping was unscoped, measured at 52.8% cross-domain
   injection (scratchpad/spread-activation-scoping-design.md §2.3). Tests
   (b)/(c) pin the fix: default scoped, opt-out via domain=None.

Runs against cortex_test (conftest.py redirects DATABASE_URL and isolates
entities/relationships/memories between tests).
"""

from __future__ import annotations

import pytest


# psycopg ships in the optional [postgresql] extra, absent from the
# SQLite-default install. The mcp_server import below pulls it in, so
# without this guard the module raises ModuleNotFoundError at COLLECTION
# time — an error, not a skip, which fails the whole run (#220). Skip the
# module cleanly instead; the PG gate below still applies when it is present.
pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: E402
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG,
    reason="PostgreSQL not available — spread_activation_memories needs live schema",
)

_DOMAIN_A = "spread-scoping-test-a"
_DOMAIN_B = "spread-scoping-test-b"


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    s.close()


def _mk_entity(store: PgMemoryStore, name: str, *, heat: float = 0.9) -> int:
    row = store._execute(
        "INSERT INTO entities (name, type, domain, origin, heat) "
        "VALUES (%s, 'technology', %s, 'text_concept', %s) RETURNING id",
        (name, _DOMAIN_A, heat),
    ).fetchone()
    store._conn.commit()
    return row["id"]


def _mem(
    store: PgMemoryStore, content: str, *, domain: str, is_global: bool = False
) -> int:
    return store.insert_memory(
        {
            "content": content,
            "source": "user",
            "domain": domain,
            "heat": 0.9,
            "is_global": is_global,
        }
    )


# ── (a) sanity: the stored procedure executes without error ────────────


def test_spread_activation_memories_executes_without_error(store: PgMemoryStore):
    """WITH RECURSIVE fix: pre-fix, every call raised
    'relation "spread" does not exist'. This is the integration test that
    was missing -- the unit suite mocks the store entirely."""
    out = store.spread_activation_memories(
        query_terms=["nonexistent-term-xyz-123"],
        min_heat=0.0,
        domain=_DOMAIN_A,
    )
    assert out == []  # no matching entity -- empty, not an exception


def test_spread_activation_memories_finds_seeded_entity(store: PgMemoryStore):
    entity_name = "AlphaWidgetScopingProbe"
    _mk_entity(store, entity_name, heat=0.9)
    _mem(store, f"a note about {entity_name} and its behavior", domain=_DOMAIN_A)

    out = store.spread_activation_memories(
        query_terms=[entity_name],
        min_heat=0.0,
        domain=_DOMAIN_A,
    )

    assert len(out) == 1


# ── (b) scoping: entity shared across two domains, default filter ──────


def test_domain_scoping_excludes_other_domain_by_default(store: PgMemoryStore):
    """A shared entity (structurally global by design) is reachable from
    memories in two different domains. domain=<A> must only surface the
    domain-A memory -- this is the fix for the measured 52.8%
    cross-domain injection rate."""
    entity_name = "SharedTokenScopingProbe"
    _mk_entity(store, entity_name, heat=0.9)
    mem_a = _mem(store, f"domain A note mentioning {entity_name}", domain=_DOMAIN_A)
    _mem(store, f"domain B note mentioning {entity_name}", domain=_DOMAIN_B)

    out = store.spread_activation_memories(
        query_terms=[entity_name],
        min_heat=0.0,
        domain=_DOMAIN_A,
    )

    ids = [mid for mid, _act in out]
    assert ids == [mem_a]


def test_domain_scoping_preserves_own_domain_recall(store: PgMemoryStore):
    """No recall loss for the requesting domain's own memory -- the filter
    is on m.domain, not e.domain (see ADR-0054)."""
    entity_name = "OwnDomainScopingProbe"
    _mk_entity(store, entity_name, heat=0.9)
    mem_a = _mem(store, f"note about {entity_name} here", domain=_DOMAIN_A)

    out = store.spread_activation_memories(
        query_terms=[entity_name],
        min_heat=0.0,
        domain=_DOMAIN_A,
    )

    assert [mid for mid, _act in out] == [mem_a]


# ── (c) cross_domain=True (domain=None) opt-out ─────────────────────────


def test_domain_none_disables_the_filter(store: PgMemoryStore):
    """domain=None (the recall_pipeline cross_domain=True path) must
    return memories from BOTH domains -- explicit opt-out, not a default."""
    entity_name = "CrossDomainOptOutProbe"
    _mk_entity(store, entity_name, heat=0.9)
    mem_a = _mem(store, f"domain A note mentioning {entity_name}", domain=_DOMAIN_A)
    mem_b = _mem(store, f"domain B note mentioning {entity_name}", domain=_DOMAIN_B)

    out = store.spread_activation_memories(
        query_terms=[entity_name],
        min_heat=0.0,
        domain=None,
    )

    ids = {mid for mid, _act in out}
    assert ids == {mem_a, mem_b}


def test_include_globals_true_surfaces_global_memory_in_other_domain(
    store: PgMemoryStore,
):
    """A memory marked is_global=True is visible from domain A even though
    it was written under domain B -- mirrors recall_memories()'s
    p_include_globals gate on the same m.domain/is_global columns."""
    entity_name = "GlobalMemoryScopingProbe"
    _mk_entity(store, entity_name, heat=0.9)
    global_mem = _mem(
        store,
        f"a globally-visible note about {entity_name}",
        domain=_DOMAIN_B,
        is_global=True,
    )

    out = store.spread_activation_memories(
        query_terms=[entity_name],
        min_heat=0.0,
        domain=_DOMAIN_A,
        include_globals=True,
    )

    assert [mid for mid, _act in out] == [global_mem]


def test_include_globals_false_hides_global_memory_in_other_domain(
    store: PgMemoryStore,
):
    entity_name = "GlobalMemoryHiddenProbe"
    _mk_entity(store, entity_name, heat=0.9)
    _mem(
        store,
        f"a globally-visible note about {entity_name}",
        domain=_DOMAIN_B,
        is_global=True,
    )

    out = store.spread_activation_memories(
        query_terms=[entity_name],
        min_heat=0.0,
        domain=_DOMAIN_A,
        include_globals=False,
    )

    assert out == []


# ── (d) min_heat threshold respected ────────────────────────────────────


def test_min_heat_threshold_excludes_cold_entity(store: PgMemoryStore):
    entity_name = "ColdEntityScopingProbe"
    _mk_entity(store, entity_name, heat=0.01)
    _mem(store, f"note mentioning {entity_name}", domain=_DOMAIN_A)

    out = store.spread_activation_memories(
        query_terms=[entity_name],
        min_heat=0.05,
        domain=_DOMAIN_A,
    )

    assert out == []


def test_min_heat_threshold_admits_hot_entity(store: PgMemoryStore):
    entity_name = "HotEntityScopingProbe"
    _mk_entity(store, entity_name, heat=0.5)
    mem_a = _mem(store, f"note mentioning {entity_name}", domain=_DOMAIN_A)

    out = store.spread_activation_memories(
        query_terms=[entity_name],
        min_heat=0.05,
        domain=_DOMAIN_A,
    )

    assert [mid for mid, _act in out] == [mem_a]
