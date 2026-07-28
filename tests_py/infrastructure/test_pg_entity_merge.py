"""Live-PG behavior tests for mutating entity merge (Action 2).

The fuzzy-dedup feature has two halves: ``core.entity_dedup`` *plans* merges
(pure, tested in tests_py/core/test_entity_dedup.py) and
``store.merge_entities`` *performs* them (this file). The consolidation cycle
``run_entity_merge_cycle`` is the composition root joining the two, gated by the
``ENTITY_DEDUP`` ablation flag.

Runs against cortex_test (conftest redirects DATABASE_URL and auto-cleans
entities/relationships/memory_entities/memories between every test).
"""

from __future__ import annotations

import os

import pytest

from mcp_server.handlers.consolidation.entity_merge import run_entity_merge_cycle
from mcp_server.infrastructure.pg_store import PgMemoryStore
from tests_py.conftest import _USE_PG  # type: ignore

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — entity merge needs live schema"
)

_DOMAIN = "entity-merge-test"


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    s.close()


def _mk_entity(
    store: PgMemoryStore,
    name: str,
    *,
    etype: str = "technology",
    origin: str = "text_concept",
    heat: float = 0.5,
) -> int:
    """Insert an entity directly, bypassing insert_entity's canonical dedup so a
    test can hold two near-duplicate rows at once."""
    row = store._execute(
        "INSERT INTO entities (name, type, domain, origin, heat) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (name, etype, _DOMAIN, origin, heat),
    ).fetchone()
    store._conn.commit()
    return row["id"]


def _mk_rel(
    store: PgMemoryStore, src: int, tgt: int, rtype: str = "related_to"
) -> None:
    store._execute(
        "INSERT INTO relationships (source_entity_id, target_entity_id, "
        "relationship_type) VALUES (%s, %s, %s)",
        (src, tgt, rtype),
    )
    store._conn.commit()


def _mem(store: PgMemoryStore, content: str) -> int:
    return store.insert_memory(
        {"content": content, "source": "user", "domain": _DOMAIN, "heat": 0.5}
    )


def _count(store: PgMemoryStore, sql: str, params: tuple) -> int:
    return store._execute(sql, params).fetchone()["c"]


# ── store.merge_entities — the mutation ────────────────────────────────────


def test_merge_rewires_memory_links(store):
    surv, alias = _mk_entity(store, "Survivor"), _mk_entity(store, "Alias")
    mem = _mem(store, "mentions the alias concept")
    store.insert_memory_entity(mem, alias)
    store._conn.commit()

    out = store.merge_entities(surv, alias)

    assert out["merged"] is True
    assert out["memory_links_moved"] == 1
    assert (
        _count(
            store, "SELECT COUNT(*) c FROM memory_entities WHERE entity_id=%s", (surv,)
        )
        == 1
    )
    assert (
        _count(
            store, "SELECT COUNT(*) c FROM memory_entities WHERE entity_id=%s", (alias,)
        )
        == 0
    )
    assert store.get_entity_by_id(alias)["archived"] is True


def test_merge_dedupes_shared_memory_link(store):
    """A memory linked to BOTH entities must not violate the (memory_id,
    entity_id) PK when the alias link is rewired onto the survivor."""
    surv, alias = _mk_entity(store, "Survivor"), _mk_entity(store, "Alias")
    mem = _mem(store, "mentions both")
    store.insert_memory_entity(mem, surv)
    store.insert_memory_entity(mem, alias)
    store._conn.commit()

    out = store.merge_entities(surv, alias)

    assert out["merged"] is True
    assert (
        _count(
            store, "SELECT COUNT(*) c FROM memory_entities WHERE entity_id=%s", (surv,)
        )
        == 1
    )


def test_merge_rewires_relationships(store):
    surv, alias = _mk_entity(store, "Survivor"), _mk_entity(store, "Alias")
    other = _mk_entity(store, "Other")
    _mk_rel(store, alias, other)

    out = store.merge_entities(surv, alias)

    assert out["relationships_rewired"] == 1
    assert (
        _count(
            store,
            "SELECT COUNT(*) c FROM relationships WHERE source_entity_id=%s",
            (surv,),
        )
        == 1
    )
    assert (
        _count(
            store,
            "SELECT COUNT(*) c FROM relationships WHERE source_entity_id=%s",
            (alias,),
        )
        == 0
    )


def test_merge_drops_self_loop(store):
    """An alias↔survivor edge would become a survivor→survivor self-loop after
    the rewire; the merge must delete it rather than leave a degenerate edge."""
    surv, alias = _mk_entity(store, "Survivor"), _mk_entity(store, "Alias")
    _mk_rel(store, alias, surv)

    store.merge_entities(surv, alias)

    assert (
        _count(
            store,
            "SELECT COUNT(*) c FROM relationships WHERE "
            "source_entity_id=target_entity_id",
            (),
        )
        == 0
    )


def test_merge_absorbs_heat_bounded(store):
    surv = _mk_entity(store, "Survivor", heat=0.3)
    alias = _mk_entity(store, "Alias", heat=0.9)

    store.merge_entities(surv, alias)

    # GREATEST, not a sum — stays within the [0,1] heat invariant.
    assert store.get_entity_by_id(surv)["heat"] == pytest.approx(0.9)


def test_merge_noop_same_id(store):
    e = _mk_entity(store, "Solo")
    assert store.merge_entities(e, e)["merged"] is False


def test_merge_noop_missing_entity(store):
    surv = _mk_entity(store, "Survivor")
    assert store.merge_entities(surv, 999_999_999)["merged"] is False


def test_merge_refuses_ast_symbol(store):
    """Code-symbol identity is structural — never fuzzy-merged. Store-level
    guard, defense in depth over the core engine's own exclusion."""
    surv = _mk_entity(store, "Survivor")
    alias = _mk_entity(store, "renderFn", etype="function", origin="ast_symbol")

    out = store.merge_entities(surv, alias)

    assert out["merged"] is False
    assert store.get_entity_by_id(alias)["archived"] is False


# ── run_entity_merge_cycle — the composition root ──────────────────────────


def test_cycle_merges_fuzzy_duplicates(store):
    keep = _mk_entity(store, "Vector Search", heat=0.9)
    dup = _mk_entity(store, "VectorSearch", heat=0.3)
    code = _mk_entity(store, "render", etype="function", origin="ast_symbol")

    result = run_entity_merge_cycle(store)

    assert result["merges_applied"] == 1
    assert store.get_entity_by_id(dup)["archived"] is True
    assert store.get_entity_by_id(keep)["archived"] is False
    assert store.get_entity_by_id(code)["archived"] is False


def test_cycle_ablated_is_noop(store):
    keep = _mk_entity(store, "Vector Search", heat=0.9)
    dup = _mk_entity(store, "VectorSearch", heat=0.3)
    os.environ["CORTEX_ABLATE_ENTITY_DEDUP"] = "1"
    try:
        result = run_entity_merge_cycle(store)
    finally:
        del os.environ["CORTEX_ABLATE_ENTITY_DEDUP"]

    assert result["ablated"] is True
    assert result["merges_applied"] == 0
    assert store.get_entity_by_id(dup)["archived"] is False
    assert store.get_entity_by_id(keep)["archived"] is False
