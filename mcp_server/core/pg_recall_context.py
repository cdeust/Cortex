"""Request-scoped context + WRRF fetch/triage for ``pg_recall.recall()``.

Split from pg_recall.py (continuing the two documented seams cut at #368 —
pg_recall_weights.py / pg_recall_assembly.py — with two more: this file and
pg_recall_stages.py) to bring pg_recall.py under this repo's local
300-line file cap and 40-line method cap (CLAUDE.md § Code Style; a
tightening of coding-standards.md §4.1/§4.2). Every value moved
unchanged — this re-homes code, it retunes nothing.

``RecallContext`` bundles the invariants of a single ``recall()`` call
(everything that does not change while ``candidates`` is threaded through
the pipeline in pg_recall_stages.py) so each stage function takes exactly
two parameters — ``(candidates, ctx)`` — instead of the 8-13 positional
parameters the inline call sites needed, per coding-standards.md §4.4
(Introduce Parameter Object over a growing parameter list).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from mcp_server.core.capture_origin import trusted_origins_at_read
from mcp_server.core.pg_recall_weights import compute_pg_weights
from mcp_server.core.query_intent import classify_query_intent
from mcp_server.core.recall_pipeline import familiarity_triage
from mcp_server.core.retrieval_dispatch import UNTRUSTED_ORIGIN_FACTOR


@dataclass(frozen=True, slots=True)
class RecallContext:
    """Invariants of one ``recall()`` call, threaded through every stage.

    Field-level rationale for the tuning knobs (mirrors the prior
    ``recall()`` docstring so no citation was lost in the split):

    - ``rerank_alpha``: blend weight for cross-encoder scores (0.70 from
      BEAM ablation).
    - ``cross_domain``: ADR-0054 opt-out for the SPREADING_ACTIVATION stage
      only (the WRRF stage stays scoped to ``domain`` regardless). Same
      "explicit opt-in, safe default" shape as ``include_globals``.
      Defaults to False: measured 52.8% cross-domain injection rate when
      this stage runs unscoped (scratchpad/spread-activation-scoping-
      design.md §2.3).
    - ``sa_mode``: ADR-0054 addendum (2026-07-11, garde x3 bench incident).
      One of ``"tail"`` (default), ``"augment"``, ``"off"``. ``"tail"``
      calls ``spreading_activation_tail_fill`` LAST, after every reranking
      stage — it only appends SA-reachable memories when the pipeline
      returned fewer than ``top_k`` candidates, never reordering or
      rescoring an existing one. ``"augment"`` runs the PRE-fusion
      ``spreading_activation_expand`` between HDC and DENDRITIC_CLUSTERS —
      the garde x3 bench's first live measurement showed it moves
      already-correct top-ranked documents even with domain scoping
      applied (LongMemEval MRR 0.9166->0.9009, floor 0.914 breach, against
      +0.002 R@10). Kept available for a future dedicated tuning campaign,
      never the default. ``"off"`` disables the channel entirely.
    - ``familiarity_shortcut``: C2 dual-process opt-in (Yonelinas 2002) —
      see ``fetch_and_triage`` below.
    """

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


def fetch_and_triage(ctx: RecallContext) -> tuple[list[dict], RecallContext, bool]:
    """Steps 1-4·C2: intent -> weights -> encode -> WRRF fetch -> triage.

    Returns ``(candidates, ctx', early_return)``: ``ctx'`` carries the
    resolved ``intent``/``q_emb`` for every later stage; ``early_return``
    is True when the caller must return ``candidates`` unchanged — an empty
    WRRF result, or FAMILIARITY_TRIAGE (Yonelinas 2002; Diana, Yonelinas &
    Ranganath 2007) choosing its opt-in shortcut on an overwhelmingly
    familiar query (ablation-guarded, non-fatal).
    """
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

    triage = familiarity_triage(
        candidates, q_emb, ctx.store, allow_shortcut=ctx.familiarity_shortcut
    )
    return triage.candidates, ctx, triage.shortcut


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
        # issue #368 — trust policy read in core, handed to the store:
        # infrastructure may not import core.
        trusted_origins=trusted_origins_at_read(),
        untrusted_factor=UNTRUSTED_ORIGIN_FACTOR,
    )
