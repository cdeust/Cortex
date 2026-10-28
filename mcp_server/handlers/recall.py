"""Handler: recall -- PG recall + production enrichments.

Composition root wiring infrastructure to core retrieval logic.

Base retrieval uses pg_recall (intent-adaptive 5-signal fusion + FlashRank reranking).
Production enrichments layer on top: prospective memory injection,
co-activation Hebbian learning, neuro-symbolic rules, strategic ordering.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core import memory_rules
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.handlers.decision_recall import (
    bounded_exact,
    exact_lookup,
)
from mcp_server.core.knowledge_graph import extract_entities
from mcp_server.core.pg_recall import recall as pg_recall
from mcp_server.core.query_intent import QueryIntent, classify_query_intent
from mcp_server.core.response_budget import ListTarget, bound_payload
from mcp_server.core.tabular_encoding import (
    encode_within_budget,
    parse_format,
    reserved_budget,
)
from mcp_server.handlers.recall_schema import schema  # noqa: F401
from mcp_server.handlers.injection_receipts import emit_injection_receipt
from mcp_server.handlers.recall_helpers import (
    annotate_source_attribution,
    build_enhancements,
    filter_by_tags,
    filter_low_signal,
    inject_triggered_memories,
    inline_related_neighbors,
)
from mcp_server.handlers.replay_tracking import track_replay_event
from mcp_server.infrastructure.embedding_engine import get_embedding_engine
from mcp_server.infrastructure.memory_config import (
    get_memory_settings,
    root_agent_topic,
)
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.session_registry import current_window_session
from mcp_server.observability import silent_failure
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled


logger = logging.getLogger(__name__)

_store: MemoryStore | None = None
_momentum_state: dict = {"momentum": 0.5}


def _resolve_session_id() -> str | None:
    """Best-effort session-identity lookup for the T1 receipt (T2-H3).

    precondition: none. postcondition: returns the current window's
    session id, or None on absence/tombstone/pid-divergence (the
    registry's contract — ``current_window_session`` returns None on every
    POSIX miss and can raise ``OSError`` on Windows, ``session_registry.py``
    module note) OR on any unforeseen exception surfacing from the registry.
    Recall's primary read path must never fail because of a blame-path side
    channel — a bare ``except Exception`` here is the named degradation mode
    (design risk/§1: a false attribution is worse than a missing one,
    and a failed recall is worse than an unattributed receipt).
    """
    try:
        return current_window_session()
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("session registry lookup failed", exc_info=True)
        return None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


# source: ADR-0430
_MIN_RESULTS_FOR_REORDER = 5


def _apply_strategic_ordering(
    results: list[dict],
    top_fraction: float = 0.3,
    bottom_fraction: float = 0.2,
) -> list[dict]:
    """Reorder to mitigate 'Lost in the Middle' (Liu et al. 2023)."""
    n = len(results)
    if n < _MIN_RESULTS_FOR_REORDER:
        return results
    top_n = max(1, int(n * top_fraction))
    bottom_n = max(1, int(n * bottom_fraction))
    if n - top_n - bottom_n <= 0:
        return results
    return results[:top_n] + results[n - bottom_n :] + results[top_n : n - bottom_n]


_MIN_CO_RETRIEVED_RESULTS = 2


def _apply_co_activation(
    results: list[dict], store: MemoryStore, settings: Any
) -> None:
    """Dragon Hatchling Hebbian: co-retrieved entities strengthen edges."""

    if is_mechanism_disabled(Mechanism.CO_ACTIVATION):
        # No-op: do not strengthen co-retrieved entity edges.
        return
    # source: ADR-0430
    if not settings.CO_ACTIVATION_ENABLED or len(results) < _MIN_CO_RETRIEVED_RESULTS:
        return
    min_score = settings.CO_ACTIVATION_MIN_SCORE
    lr = settings.CO_ACTIVATION_LEARNING_RATE
    entity_sets: list[set[str]] = []
    for r in results[:5]:
        if r.get("score", 0) < min_score:
            continue
        ents = extract_entities(r.get("content", ""))
        entity_sets.append({e["name"] for e in ents})
    try:
        for i, ents_a in enumerate(entity_sets):
            for ents_b in entity_sets[i + 1 :]:
                for a in list(ents_a)[:5]:
                    for b in list(ents_b)[:5]:
                        if a != b:
                            store.reinforce_or_create_relationship(a, b, lr)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("recall.hebbian_co_activation")
        silent_failure.note("recall.hebbian_co_activation", exc)


def _apply_rules_and_order(
    results: list[dict], store: MemoryStore, settings: Any, max_results: int
) -> list[dict]:
    """Apply neuro-symbolic rules and strategic ordering."""
    try:
        rules = store.get_all_active_rules()
        if rules:
            results = memory_rules.apply_rules(results, rules, score_field="score")
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("recall.neuro_symbolic_rules")
        silent_failure.note("recall.neuro_symbolic_rules", exc)
    results = results[:max_results]
    if settings.STRATEGIC_ORDERING_ENABLED:
        results = _apply_strategic_ordering(
            results, settings.STRATEGIC_TOP_FRACTION, settings.STRATEGIC_BOTTOM_FRACTION
        )
    return results


def _track_recall_replay(results: list[dict], store: Any) -> None:
    """Track a hippocampal replay event for each recalled memory.

    Each recall event counts as a hippocampal replay (McClelland 1995). This
    drives consolidation stage advancement through the cascade and CLS-B
    hippocampal-dependency decay (see ``replay_tracking.track_replay_event``).
    """
    for mem in results:
        mem_id = mem.get("memory_id") or mem.get("id")
        if mem_id is None:
            continue
        track_replay_event(mem_id, store)


def _fetch_by_id(
    memory_id: int, content_offset: int, fmt: str = "json"
) -> dict[str, Any]:
    """Fetch one memory by id — the retrieval path for truncated results.

    ``content_offset`` pages through contents larger than the response
    budget: the slice starts there, ``content_length`` carries the full
    size, and ``bound_payload`` marks the slice ``truncated`` if it
    still overflows. ``fmt`` is honored for a self-describing response, but a
    single-item list rarely benefits from tabular encoding — the budget
    re-check in ``encode_within_budget`` keeps whichever form fits.
    """
    stored = _get_store().get_memory(memory_id)
    # Connection-rooted fetch must not disclose another agent's content or ID.
    # Unlike search's existing agent boost, this new ID surface enforces scope.
    root = root_agent_topic()
    if stored is None or (root is not None and stored.get("agent_context") != root):
        return encode_within_budget(
            {"memories": [], "count": 0, "intent": "general"}, "memories", fmt
        )
    # Copy before mutating: truncation must never write back into
    # whatever object the store handed us.
    memory = {**stored}
    content = memory.get("content") or ""
    if content_offset > 0:
        memory["content"] = content[content_offset:]
    memory["content_length"] = len(content)
    memory["content_offset"] = content_offset
    resp = {"memories": [memory], "count": 1, "intent": "general"}
    settings = get_memory_settings()
    # Bound against the RESERVED budget so appending the self-describing
    # ``format`` field below cannot push the payload past the host cap.
    resp = bound_payload(
        resp,
        [ListTarget("memories", weight_key="score")],
        reserved_budget(settings.MAX_RESPONSE_CHARS),
    )
    return encode_within_budget(resp, "memories", fmt, settings.MAX_RESPONSE_CHARS)


async def _handler_impl(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Retrieve memories: pg_recall base + production enrichments."""
    if args and (args.get("memory_id") is None or args.get("exact_id")):
        exact = exact_lookup(args)
        if exact is not None:
            return bounded_exact(exact, args)
    fmt = parse_format(args.get("format") if args else None)
    if args and args.get("memory_id") is not None:
        return _fetch_by_id(
            int(args["memory_id"]), int(args.get("content_offset") or 0), fmt
        )
    if not args or not args.get("query"):
        # source: ADR-0430
        return encode_within_budget(
            {"memories": [], "count": 0, "intent": "semantic"}, "memories", fmt
        )

    query = args["query"]
    domain, directory = args.get("domain"), args.get("directory")
    agent_topic = args.get("agent_topic")
    # Connection-rooted scoping: when the server is launched with
    # CORTEX_ROOT_AGENT_TOPIC, force that scope regardless of what the
    # caller passed (or omitted). Defense at the handler boundary covers
    # every caller, not just the schema-stripped tool surface.
    _root = root_agent_topic()
    if _root is not None:
        agent_topic = _root
    max_results = args.get("max_results", 10)
    min_heat = args.get("min_heat", 0.05)
    include_low_signal = bool(args.get("include_low_signal", False))
    include_related = bool(args.get("include_related", False))
    cross_domain = bool(args.get("cross_domain", False))
    sa_mode = str(args.get("sa_mode") or "tail")
    tags_any: list[str] = list(args.get("tags_any") or [])
    tags_all: list[str] = list(args.get("tags_all") or [])
    settings = get_memory_settings()
    store, emb = _get_store(), get_embedding_engine()

    # Base retrieval: pg_recall (intent → PG weights → recall_memories → rerank).
    # Over-fetch when filtering is on so that after low-signal drops we
    # still surface ``max_results`` curated items. Tool-output captures
    # are common enough that a 3× headroom is a reasonable starting
    # point — the alternative is iterative refill, which complicates
    # the rerank ordering.
    fetch_k = max_results * 3 if not include_low_signal else max_results
    results = pg_recall(
        query=query,
        store=store,
        embeddings=emb,
        top_k=fetch_k,
        domain=domain,
        directory=directory,
        agent_topic=agent_topic,
        min_heat=min_heat,
        wrrf_k=settings.WRRF_K,
        momentum_state=_momentum_state,
        cross_domain=cross_domain,
        sa_mode=sa_mode,
    )

    # source: ADR-0430
    low_signal_dropped = 0
    if not include_low_signal:
        results, low_signal_dropped = filter_low_signal(results)

    # Positive tag filter: tags_any (OR) and tags_all (AND).
    # Applied at the same pipeline stage as the low-signal filter so the
    # over-fetch headroom above still applies.
    if tags_any or tags_all:
        results = filter_by_tags(results, tags_any, tags_all)

    # Cap to the caller-requested max_results after filtering.
    results = results[:max_results]

    # Production enrichments on top of base retrieval
    results = inject_triggered_memories(results, query, store, max_inject=max_results)
    _apply_co_activation(results, store, settings)
    results = _apply_rules_and_order(results, store, settings, max_results)

    # Track access + replay for consolidation cascade
    # Biological basis: retrieval = hippocampal replay (McClelland 1995)
    # Each recall increments replay_count, driving stage advancement
    _track_recall_replay(results, store)

    # Inline relation-walk (item 3): opt-in one-hop neighbors per surfaced
    # memory. Runs on the capped result set only, after final ordering, so
    # the fanout is bounded by max_results and stays well under the full
    # context assembler. Off by default — flat recall is unchanged.
    if include_related:
        inline_related_neighbors(results, store)

    # C1 read-side surfacing (source/reality monitoring): annotate each hit with
    # its stored source_attribution (now flowed through the recall_memories
    # projection) and a per-hit confabulation_risk flag. STRICTLY ADDITIVE —
    # writes two keys per result, never reorders/drops/injects. Ablation-guarded
    # (CORTEX_ABLATE_CONFABULATION_GATE=1 leaves confabulation_risk False).
    annotate_source_attribution(results)

    intent_info = classify_query_intent(query)
    intent = intent_info.get("intent", QueryIntent.GENERAL)
    # source: ADR-0430
    resp = {
        "memories": results,
        "count": len(results),
        "intent": str(intent),
        "low_signal_dropped": low_signal_dropped,
        "dispatch_tier": "pg",
        "signals": {},
        "enhancements": build_enhancements(query, intent, "pg", settings),
    }
    # source: ADR-0430
    resp = bound_payload(
        resp,
        [ListTarget("memories", weight_key="score")],
        reserved_budget(settings.MAX_RESPONSE_CHARS),
    )
    resp["count"] = len(resp["memories"])
    # source: ADR-0430
    receipt_id = emit_injection_receipt(
        store, resp["memories"], session_id=_resolve_session_id()
    )
    if receipt_id is not None:
        resp["receipt_id"] = receipt_id
    # source: ADR-0430
    return encode_within_budget(resp, "memories", fmt, settings.MAX_RESPONSE_CHARS)


# source: ADR-0430
handler = instrument("recall", _handler_impl, result_count_key="memories")
