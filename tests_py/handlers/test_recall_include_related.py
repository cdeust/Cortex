"""Inline relation-walk recall mode (borrow-from-supermemory item 3).

recall(include_related=True) attaches a ONE-HOP walk to each surfaced memory:
  - related.versions  — supersession-chain neighbors (reuses item 1's edges)
  - related.entities  — directly related entities via the knowledge graph

It is a cheap mid-tier enrichment, distinct from the full PageRank/HippoRAG
context assembler. This file proves the behavior end-to-end against live PG
and guards the latency stays bounded (within a small factor of flat recall,
NOT the whole-graph assembler — the walk is one hop with bounded fanout).

External signals (handover acceptance):
  - neighbors are present inline only when include_related=True;
  - the enriched recall latency is bounded (mid-tier, not the assembler).
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from mcp_server.handlers import recall
from mcp_server.infrastructure.pg_store import PgMemoryStore
from tests_py.conftest import _USE_PG_STORE  # type: ignore

pytestmark = pytest.mark.skipif(
    # Gated on the EFFECTIVE backend, not reachability: these fixtures seed
    # PostgreSQL directly (raw DSN / PG-only migrations) while the product
    # under test reads the resolved store. Under a sqlite-backend run they
    # seeded one store and asserted against another, so they failed for a
    # harness reason rather than a product one. SQLite coverage of these
    # paths needs backend-agnostic fixtures — tracked in #220.
    not _USE_PG_STORE,
    reason="PostgreSQL not available — relation-walk needs live schema",
)

_DOMAIN = "include-related-test"
_DIM = 384


def _emb() -> bytes:
    rng = np.random.default_rng(1)
    base = rng.standard_normal(_DIM).astype(np.float32)
    base /= np.linalg.norm(base)
    return base.tobytes()


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    try:
        s._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
        # Relationships FK-reference entities — drop them before the entities.
        s._execute(
            "DELETE FROM relationships WHERE source_entity_id IN "
            "(SELECT id FROM entities WHERE domain = %s) "
            "OR target_entity_id IN (SELECT id FROM entities WHERE domain = %s)",
            (_DOMAIN, _DOMAIN),
        )
        s._execute("DELETE FROM entities WHERE domain = %s", (_DOMAIN,))
        s._conn.commit()
    finally:
        s.close()


def _seed(store: PgMemoryStore) -> dict:
    """Seed a superseded/current memory pair plus a 2-entity relationship."""
    common = {"embedding": _emb(), "source": "user", "domain": _DOMAIN, "heat": 0.6}
    old_id = store.insert_memory(
        {**common, "content": "deploy target is staging alpha relation walk"}
    )
    # Atomic insert + supersession edge (both directions) in one call.
    new_id, _ = store.supersede_atomic(
        {**common, "content": "deploy target is staging alpha relation walk"}, old_id
    )

    e_deploy = store.insert_entity(
        {"name": "deploy-alpha", "type": "concept", "domain": _DOMAIN}
    )
    e_server = store.insert_entity(
        {"name": "staging-server", "type": "concept", "domain": _DOMAIN}
    )
    store.insert_memory_entity(new_id, e_deploy)
    store.insert_relationship(
        {
            "source_entity_id": e_deploy,
            "target_entity_id": e_server,
            "relationship_type": "targets",
            "weight": 2.0,
        }
    )
    return {"old_id": old_id, "new_id": new_id, "server_entity": "staging-server"}


def _recall(include_related: bool):
    return asyncio.run(
        recall.handler(
            {
                "query": "deploy target staging alpha relation walk",
                "domain": _DOMAIN,
                "max_results": 10,
                "min_heat": 0.0,
                "include_related": include_related,
            }
        )
    )


def test_flat_recall_has_no_related(store):
    _seed(store)
    resp = _recall(include_related=False)
    assert resp["memories"], "expected at least one hit"
    assert all("related" not in m for m in resp["memories"])


def test_include_related_inlines_version_and_entity_neighbors(store):
    seed = _seed(store)
    resp = _recall(include_related=True)
    by_id = {m.get("memory_id") or m.get("id"): m for m in resp["memories"]}
    current = by_id.get(seed["new_id"])
    assert current is not None, "current version must surface"
    related = current["related"]

    # Version axis: the current row points back at the fact it superseded.
    version_ids = {v["memory_id"] for v in related["versions"]}
    assert seed["old_id"] in version_ids
    assert any(v["edge"] == "supersedes" for v in related["versions"])

    # Entity axis: one hop from deploy-alpha reaches staging-server.
    neighbor_names = {n["name"] for e in related["entities"] for n in e["neighbors"]}
    assert seed["server_entity"] in neighbor_names


def test_include_related_latency_is_bounded(store):
    """The walk is mid-tier: enriched recall stays within a small factor of
    flat recall (one-hop bounded fanout), not the full-graph assembler."""
    _seed(store)
    # Warm caches with one untimed call each.
    _recall(include_related=False)
    _recall(include_related=True)

    t0 = time.perf_counter()
    _recall(include_related=False)
    t_flat = time.perf_counter() - t0

    t0 = time.perf_counter()
    _recall(include_related=True)
    t_related = time.perf_counter() - t0

    # Generous bound: bounded one-hop enrichment must not be an order of
    # magnitude over flat recall. (Structural guarantee vs the assembler:
    # <=3 entities x <=5 neighbors + <=2 version lookups per hit, no
    # whole-graph PageRank.) Add a small floor so sub-ms jitter never trips.
    assert t_related < max(t_flat * 8.0, 0.5), (
        f"relation-walk latency {t_related:.4f}s exceeded bound (flat {t_flat:.4f}s)"
    )
