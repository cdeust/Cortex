"""Request-scoped context + WRRF fetch/triage for ``pg_recall.recall()``.

source: ADR-0218"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.capture_origin import trusted_origins_at_read
from mcp_server.core.pg_recall_weights import compute_pg_weights
from mcp_server.core.query_intent import classify_query_intent
from mcp_server.core.recall_pipeline import familiarity_triage
from mcp_server.core.retrieval_dispatch import untrusted_origin_factor
from mcp_server.shared.memory_embeddings import MemoryEmbeddings


@dataclass(frozen=True, slots=True)
class RecallContext:
    """Invariants of one ``recall()`` call, threaded through every stage.

    source: ADR-0218"""

    query: str
    store: Any
    embeddings: Any
    domain: str | None
    directory: str | None
    agent_topic: str | None
    min_heat: float
    wrrf_k: int
    include_globals: bool
    cross_domain: bool
    sa_mode: str
    rerank: bool
    rerank_alpha: float
    familiarity_shortcut: bool
    top_k: int
    momentum_state: dict | None
    # Resolved by fetch_and_triage() (step 1-3, before the WRRF fetch);
    # unset (None) on the context recall() constructs.
    intent: Any = None
    q_emb: Any = None
    candidate_embeddings: MemoryEmbeddings | None = None


def fetch_and_triage(ctx: RecallContext) -> tuple[list[dict], RecallContext, bool]:
    """Steps 1-4·C2: intent -> weights -> encode -> WRRF fetch -> triage.

    source: ADR-0218"""
    intent_info = classify_query_intent(ctx.query)
    intent = intent_info["intent"]
    weights = compute_pg_weights(intent, intent_info.get("weights", {}))
    # No char truncation: the embedding model enforces its own token limit
    # internally (e.g. 256 for MiniLM, 512 for bge-*, 8192 for bge-m3/jina-v3).
    q_emb = ctx.embeddings.encode(ctx.query) if ctx.embeddings else None
    ctx = replace(ctx, intent=intent, q_emb=q_emb)

    candidates = _wrrf_fetch(ctx, weights)
    if not candidates:
        return [], ctx, True

    ctx = _observe_candidate_embeddings(ctx, candidates)
    triage = familiarity_triage(
        candidates,
        q_emb,
        ctx.candidate_embeddings if ctx.candidate_embeddings is not None else ctx.store,
        allow_shortcut=ctx.familiarity_shortcut,
    )
    return triage.candidates, ctx, triage.shortcut


def _observe_candidate_embeddings(
    ctx: RecallContext, candidates: list[dict]
) -> RecallContext:
    """Familiarity and Hopfield are consecutive and perform no writes.

    source: ADR-0218"""
    if ctx.q_emb is None or not hasattr(ctx.store, "get_embeddings_for_memories"):
        return ctx
    if all(
        is_mechanism_disabled(mechanism)
        for mechanism in (Mechanism.DUAL_PROCESS, Mechanism.HOPFIELD)
    ):
        return ctx
    snapshot = MemoryEmbeddings.read(ctx.store, [c["memory_id"] for c in candidates])
    return replace(ctx, candidate_embeddings=snapshot)


def _wrrf_fetch(ctx: RecallContext, weights: dict) -> list[dict]:
    """Step 4: PG ``recall_memories()`` — server-side WRRF fusion."""
    intent = ctx.intent
    return ctx.store.recall_memories(
        query_text=ctx.query,
        query_embedding=ctx.q_emb,
        intent=str(intent.value) if hasattr(intent, "value") else str(intent),
        domain=ctx.domain,
        directory=ctx.directory,
        agent_topic=ctx.agent_topic,
        min_heat=ctx.min_heat,
        max_results=ctx.top_k,
        wrrf_k=ctx.wrrf_k,
        weights=weights,
        include_globals=ctx.include_globals,
        # source: ADR-0218
        trusted_origins=trusted_origins_at_read(),
        untrusted_factor=untrusted_origin_factor(),
    )
