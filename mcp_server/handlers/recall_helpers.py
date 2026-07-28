"""Helpers for the recall handler — signal collection and result building.

Extracted to keep recall.py under 300 lines with all methods under 40 lines.
"""

from __future__ import annotations

import json
from typing import Any

from mcp_server.core import thermodynamics
from mcp_server.core.enrichment import build_expanded_query
from mcp_server.shared.code_tokenize import expand_fts_query
from mcp_server.core.prospective import check_trigger
from mcp_server.core.query_intent import QueryIntent
from mcp_server.core.retrieval_signals import (
    compute_graph_signals,
    compute_hopfield_hdc,
)
from mcp_server.core.scoring import compute_bm25_scores, compute_ngram_score
from mcp_server.core.temporal import compute_recency_boost
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.observability import silent_failure
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.source_monitoring import recall_confabulation_risk


def compute_vector_fts(
    query: str,
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    pool: int,
    min_heat: float,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]], Any]:
    """Vector similarity + FTS5 signals."""
    q_emb = embeddings.encode(query)
    vec: list[tuple[int, float]] = []
    if q_emb:
        vec = [
            (m, 1.0 / (1.0 + d))
            for m, d in store.search_vectors(q_emb, top_k=pool, min_heat=min_heat)
        ]
    expanded = build_expanded_query(query)
    fts = store.search_fts(expanded, limit=pool)
    if expanded != query:
        ids = {m for m, _ in fts}
        fts.extend(
            (m, s) for m, s in store.search_fts(query, limit=pool // 2) if m not in ids
        )
    # Code-aware discovery (issue #169): a camelCase/snake_case query term is
    # expanded into its sub-tokens so a lowercase query ("payment") recalls a
    # symbol memory ("normalizePaymentAmount") on the SQLite FTS path — and vice
    # versa. Merge-in only (never removes a hit); the raw/expanded searches
    # above stay primary, so this is additive on both backends.
    code_q = expand_fts_query(query)
    if code_q and code_q not in (query, expanded):
        ids = {m for m, _ in fts}
        fts.extend(
            (m, s) for m, s in store.search_fts(code_q, limit=pool // 2) if m not in ids
        )
    return vec, fts, q_emb


def compute_text_signals(
    query: str,
    hot_mems: list[dict],
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """BM25 + n-gram signals from hot memory pool."""
    if not hot_mems:
        return [], []
    ids = [m["id"] for m in hot_mems]
    docs = [m.get("content", "") for m in hot_mems]
    bm25 = [(mid, s) for mid, s in zip(ids, compute_bm25_scores(query, docs)) if s > 0]
    ngram = [
        (m["id"], compute_ngram_score(query, m.get("content", ""))) for m in hot_mems
    ]
    return bm25, [(mid, s) for mid, s in ngram if s > 0]


def get_hot_pool(
    store: MemoryStore,
    domain: str | None,
    directory: str | None,
    min_heat: float,
    pool: int,
) -> list[dict]:
    """Fetch hot memories scoped by domain/directory."""
    if domain:
        return store.get_memories_for_domain(domain, min_heat=min_heat, limit=pool)
    if directory:
        return store.get_memories_for_directory(directory, min_heat=min_heat)
    return store.get_hot_memories(min_heat=min_heat, limit=pool)


def collect_signals(
    query: str,
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    settings: Any,
    pool: int,
    min_heat: float,
    domain: str | None,
    directory: str | None,
) -> dict[str, list]:
    """Collect all 9 retrieval signals."""
    vec, fts, q_emb = compute_vector_fts(query, store, embeddings, pool, min_heat)
    hot = get_hot_pool(store, domain, directory, min_heat, pool)
    hop, hdc = compute_hopfield_hdc(
        query, q_emb, store, embeddings, hot, settings, pool, min_heat
    )
    sr, sa = compute_graph_signals(query, store, vec, min_heat, settings, pool)
    bm25, ngram = compute_text_signals(query, hot)
    return {
        "vector": vec,
        "fts": fts,
        "heat": [(m["id"], m["heat"]) for m in hot],
        "hopfield": hop,
        "hdc": hdc,
        "sr": sr,
        "sa": sa,
        "bm25": bm25,
        "ngram": ngram,
    }


def compute_result_boost(intent: str, created_at: str, settings: Any) -> float:
    """Compute recency boost based on query intent."""
    if intent == QueryIntent.KNOWLEDGE_UPDATE:
        return compute_recency_boost(
            created_at,
            boost_max=settings.RECENCY_BOOST_MAX * 3.0,
            halflife_days=settings.RECENCY_BOOST_HALFLIFE_DAYS * 0.5,
            cutoff_days=settings.RECENCY_BOOST_CUTOFF_DAYS * 2.0,
        )
    return compute_recency_boost(
        created_at,
        boost_max=settings.RECENCY_BOOST_MAX,
        halflife_days=settings.RECENCY_BOOST_HALFLIFE_DAYS,
        cutoff_days=settings.RECENCY_BOOST_CUTOFF_DAYS,
    )


def parse_tags(tags: Any) -> list:
    """Normalize tags from string or list form."""
    if isinstance(tags, str):
        try:
            return json.loads(tags)
        except (ValueError, TypeError):
            return []
    return tags if tags else []


# Low-signal tags: memories so tagged are auto-captures from tool
# operations, backfill imports, or stage reports — useful for audit
# replay but noise in semantic recall.
#
# Spike 2026-05-13: three diverse queries about ADR-2244 design
# decisions returned exclusively ``# Tool: Edit`` captures from
# unrelated repos. The curated wiki (31 ADRs + 21 lessons + 54
# conventions) was drowned out because every captured tool call
# scores high on WRRF + heat + recency.
#
# The wiki classifier (``mcp_server.core.wiki_classifier_patterns.AUDIT_TAGS``)
# already maintains this concept and rejects such content from the
# wiki. Recall reuses the same idea at the retrieval layer.
LOW_SIGNAL_TAGS: frozenset[str] = frozenset(
    {
        "auto-captured",
        "_backfill",
        "imported",
        "session-summary",
        "tool-output",
        "code-review",
        "tool:edit",
        "tool:bash",
        "tool:read",
        "tool:write",
        "tool:grep",
        "tool:glob",
        "tool:search",
        "tool:webfetch",
        "tool:websearch",
        "tool:notebookedit",
        "stage-1",
        "stage-2",
        "stage-3",
        "stage-4",
        "stage-5",
        "stage-6",
        "stage-7",
        "stage-8",
        "stage-9",
        "stage-10",
        "stage-11",
        "audit",
        "automated",
        "wip",
        "progress",
    }
)


def filter_low_signal(results: list[dict]) -> tuple[list[dict], int]:
    """Drop memories whose tags mark them as low-signal noise.

    Returns ``(kept_results, dropped_count)``. The dropped count is
    surfaced in the response so callers see how much was filtered —
    important for debugging the "why didn't I get the result I expected"
    case.

    Callers that explicitly want low-signal memories (debugging,
    replay tooling) skip this filter via the ``include_low_signal``
    input parameter on the recall handler.
    """
    kept: list[dict] = []
    dropped = 0
    for r in results:
        tags = r.get("tags", [])
        if isinstance(tags, str):
            tags = parse_tags(tags)
        tag_set = {str(t).lower() for t in tags}
        if tag_set & LOW_SIGNAL_TAGS:
            dropped += 1
            continue
        kept.append(r)
    return kept, dropped


def filter_by_tags(
    results: list[dict],
    tags_any: list[str],
    tags_all: list[str],
) -> list[dict]:
    """Positive tag filter applied after the WRRF pipeline.

    Precondition:  results is the post-low-signal-filter list; tags_any and
                   tags_all are lists of lowercase tag strings (may be empty).
    Postcondition: returns the subset of results satisfying both constraints:
                   - tags_any: memory carries at least one tag in tags_any
                     (OR semantics); skipped when tags_any is empty.
                   - tags_all: memory carries every tag in tags_all
                     (AND semantics); skipped when tags_all is empty.
    Invariant:     len(result) <= len(results); order is preserved.

    Passing tags_any=[\"archival\"] returns only archival-tagged memories.
    """
    if not tags_any and not tags_all:
        return results

    any_set = {str(t).lower() for t in tags_any}
    all_set = {str(t).lower() for t in tags_all}

    kept: list[dict] = []
    for r in results:
        raw_tags = r.get("tags", [])
        if isinstance(raw_tags, str):
            raw_tags = parse_tags(raw_tags)
        tag_set = {str(t).lower() for t in raw_tags}

        if any_set and not (tag_set & any_set):
            continue
        if all_set and not all_set.issubset(tag_set):
            continue
        kept.append(r)
    return kept


def build_result(mem: dict, score: float, intent: str, settings: Any) -> dict:
    """Build a single result dict with recency boost."""
    created_at = mem.get("created_at", "")
    heat = thermodynamics.compute_session_coherence(
        mem["heat"],
        created_at,
        bonus=settings.SESSION_COHERENCE_BONUS,
        window_hours=settings.SESSION_COHERENCE_WINDOW_HOURS,
    )
    boost = compute_result_boost(intent, created_at, settings)
    return {
        "memory_id": mem["id"],
        "content": mem["content"],
        "score": round(score * (1.0 + boost), 4),
        "heat": round(heat, 4),
        "domain": mem.get("domain", ""),
        "tags": parse_tags(mem.get("tags", [])),
        "store_type": mem.get("store_type", "episodic"),
        "created_at": created_at,
        "importance": mem.get("importance", 0.5),
        "surprise": mem.get("surprise_score", 0.0),
        "recency_boost": round(boost, 4),
    }


def inject_triggered_memories(
    results: list[dict],
    query: str,
    store: Any,
    max_inject: int | None = None,
) -> list[dict]:
    """Inject prospective memories whose triggers match the query.

    Standing instructions like "Always X when I ask about Y" are stored
    as prospective memories. When a query matches their trigger, the
    associated memory is injected into results even if WRRF didn't find it.

    Bounded-io Phase 2 F1 (docs/provenance/bounded-io-phase2-design.md M1): the
    2026-06-10 audit found this injection was the PRIMARY live scoring
    inversion — 317 garbage triggers each prepending up to 3 FTS matches
    at a fabricated 0.9, unbounded, re-introducing the exact auto-capture
    blobs filter_low_signal had just dropped. Now: injected candidates
    respect the same low-signal taxonomy (LOW_SIGNAL_TAGS + auto-capture
    source), the total is capped at ``max_inject`` (the caller-requested
    k — injection must not exceed the tool's response contract), and each
    item carries ``injected: True`` so the fabricated 0.9 is observable
    as trigger metadata, not a covert rank.
    """
    try:
        triggers = store.get_active_prospective_memories()
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("recall_helpers.prospective_triggers", exc)
        return results
    if not triggers:
        return results
    existing_ids = {r["memory_id"] for r in results}
    injected: list[dict] = []
    for t in triggers:
        if max_inject is not None and len(injected) >= max_inject:
            break
        if not check_trigger(t, content=query):
            continue
        matches = store.search_fts(t.get("content", ""), limit=3)
        for mid, _score in matches:
            if max_inject is not None and len(injected) >= max_inject:
                break
            if mid in existing_ids:
                continue
            mem = store.get_memory(mid)
            if not mem or not _injectable(mem):
                continue
            injected.append(
                {
                    "memory_id": mid,
                    "content": mem["content"],
                    "score": 0.9,
                    "injected": True,
                    "source": mem.get("source", ""),
                    "heat": mem.get("heat", 1.0),
                    "domain": mem.get("domain", ""),
                    "tags": parse_tags(mem.get("tags", [])),
                    "store_type": mem.get("store_type", "episodic"),
                    "created_at": mem.get("created_at", ""),
                    "importance": mem.get("importance", 0.5),
                    "surprise": mem.get("surprise_score", 0.0),
                    "recency_boost": 0.0,
                }
            )
            existing_ids.add(mid)
    return injected + results if injected else results


def _injectable(mem: dict) -> bool:
    """Trigger injection must not bypass the low-signal discipline.

    Auto-captured tool dumps and tag-marked noise are exactly what
    filter_low_signal removes from the ranked results upstream;
    re-inserting them here at a fixed 0.9 inverted the ranking.
    """
    if mem.get("source") == "post_tool_capture":
        return False
    tags = {str(t).lower() for t in parse_tags(mem.get("tags", []))}
    return not (tags & LOW_SIGNAL_TAGS)


def build_enhancements(query: str, intent: str, tier: str, settings: Any) -> dict:
    """Build the enhancements metadata for the response."""
    return {
        "query_expanded": build_expanded_query(query) != query,
        "multihop_applied": tier == "mixed",
        "reranked": True,
        "knowledge_update_boost": intent == QueryIntent.KNOWLEDGE_UPDATE,
        "strategic_ordering": settings.STRATEGIC_ORDERING_ENABLED,
    }


# ── Inline relation-walk (borrow-from-supermemory item 3) ──────────────────
# A cheap mid-tier enrichment that sits between flat recall and the heavy
# 3-phase context assembler (PageRank/HippoRAG): for each recalled memory,
# inline a ONE-HOP walk over (a) the supersession version chain (item 1) and
# (b) the entity relationship graph. Opt-in via recall(include_related=True);
# OFF in every benchmark loader, so it never touches benchmarked scores.
#
# max_entities / max_neighbors are response-budget fanout caps (cf.
# core/response_budget.py), NOT algorithmic constants — they shape payload
# size only, are tunable, and are benchmark-irrelevant. _GIST_CHARS likewise
# bounds the inlined neighbor preview.
_GIST_CHARS = 160


def _version_neighbors(memory_id: int, store: MemoryStore) -> list[dict[str, Any]]:
    """Supersession-chain neighbors of a memory (item-1 edges), if any."""
    row = store.get_memory(memory_id)
    if not row:
        return []
    out: list[dict[str, Any]] = []
    for edge, key in (
        ("supersedes", "supersedes_id"),
        ("superseded_by", "superseded_by_id"),
    ):
        nid = row.get(key)
        if not nid:
            continue
        neighbor = store.get_memory(int(nid))
        if neighbor:
            out.append(
                {
                    "memory_id": int(nid),
                    "edge": edge,
                    "gist": str(neighbor.get("content", ""))[:_GIST_CHARS],
                }
            )
    return out


def _entity_neighbors(
    memory_id: int, store: MemoryStore, max_entities: int, max_neighbors: int
) -> list[dict[str, Any]]:
    """One-hop entity relationship neighbors for a memory's top entities."""
    entities = store.get_entities_for_memory(memory_id)[:max_entities]
    out: list[dict[str, Any]] = []
    for ent in entities:
        rels = store.get_relationships_for_entity(
            ent["id"], direction="outgoing", limit=max_neighbors
        )
        neighbors = [
            {
                "name": r.get("target_name"),
                "relationship_type": r.get("relationship_type"),
                "weight": r.get("weight"),
            }
            for r in rels
        ]
        if neighbors:
            out.append({"entity": ent.get("name"), "neighbors": neighbors})
    return out


def inline_related_neighbors(
    results: list[dict[str, Any]],
    store: MemoryStore,
    *,
    max_entities: int = 3,
    max_neighbors: int = 5,
) -> None:
    """Attach a one-hop relation walk to each recalled memory, in place.

    Adds ``related = {"versions": [...], "entities": [...]}`` to every result
    dict. ``versions`` reuses the item-1 supersession edges (the fact this
    row replaced and the one that replaced it); ``entities`` is a weight-
    ranked one-hop walk over the entity graph. Bounded fanout keeps this
    distinct from — and cheaper than — the full context assembler.
    """
    for mem in results:
        mid = mem.get("memory_id") or mem.get("id")
        if mid is None:
            continue
        mem["related"] = {
            "versions": _version_neighbors(int(mid), store),
            "entities": _entity_neighbors(int(mid), store, max_entities, max_neighbors),
        }


def annotate_source_attribution(results: list[dict[str, Any]]) -> None:
    """Surface C1 source/reality-monitoring provenance on each recall hit, in place.

    Additive read-side surfacing of the ``source_attribution`` the recall
    projection now returns (pg_schema.recall_memories → pg_store dict → here):

      - ``source_attribution`` — the memory's stored epistemic origin
        (perceived / told / inferred / unknown), defaulted to 'unknown' when the
        column/value is absent (older store or un-classified row).
      - ``confabulation_risk`` — the per-hit reality-monitoring flag
        (``source_monitoring.recall_confabulation_risk``): True only when the
        memory was stored as PERCEIVED but its content now classifies as INFERRED
        with zero perceptual grounding (Johnson & Raye 1981). A memory stored as
        inferred/told/unknown makes no external-grounding promise and is never
        flagged.

    STRICTLY ADDITIVE: it only writes those two keys onto each existing result
    dict; it never reorders, drops, or injects results. Disabled when
    ``Mechanism.CONFABULATION_GATE`` is ablated
    (``CORTEX_ABLATE_CONFABULATION_GATE=1``) — in that case each hit still gets
    its ``source_attribution`` (pure provenance passthrough) but ``confabulation
    _risk`` is left False, so the gate contributes nothing to the response.
    """

    gate_on = not is_mechanism_disabled(Mechanism.CONFABULATION_GATE)
    for mem in results:
        attribution = mem.get("source_attribution") or "unknown"
        mem["source_attribution"] = attribution
        mem["confabulation_risk"] = bool(
            gate_on
            and recall_confabulation_risk(mem.get("content", "") or "", attribution)
        )
