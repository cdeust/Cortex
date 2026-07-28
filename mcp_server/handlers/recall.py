"""Handler: recall -- PG recall + production enrichments.

Composition root wiring infrastructure to core retrieval logic.

Base retrieval uses pg_recall (intent-adaptive PG WRRF + FlashRank reranking).
Production enrichments layer on top: prospective memory injection,
co-activation Hebbian learning, neuro-symbolic rules, strategic ordering.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core import memory_rules
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.core.knowledge_graph import extract_entities
from mcp_server.core.pg_recall import recall as pg_recall
from mcp_server.core.query_intent import QueryIntent, classify_query_intent
from mcp_server.core.response_budget import ListTarget, bound_payload
from mcp_server.core.tabular_encoding import (
    encode_within_budget,
    parse_format,
    reserved_budget,
)
from mcp_server.handlers._tool_meta import NON_IDEMPOTENT_WRITE
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

schema = {
    "title": "Recall (retrieve memories)",
    "annotations": NON_IDEMPOTENT_WRITE,
    "outputSchema": {
        "type": "object",
        "required": ["memories"],
        "properties": {
            "memories": {
                "type": "array",
                "description": (
                    "Ranked list of matching memories. Best result is index 0. "
                    'With ``format: "json"`` (default) each element is a '
                    'memory object; with ``format: "tabular"`` each element '
                    "is a cell array whose fields are named once in the "
                    "sibling ``columns`` header (issue #170)."
                ),
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Memory UUID.",
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Memory body.",
                                },
                                "score": {
                                    "type": "number",
                                    "description": "Final fused + reranked score.",
                                },
                                "heat": {
                                    "type": "number",
                                    "description": "Current thermodynamic heat [0,1].",
                                },
                                "domain": {"type": "string"},
                                "tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "created_at": {
                                    "type": "string",
                                    "format": "date-time",
                                },
                                "source": {"type": "string"},
                                "truncated": {
                                    "type": "boolean",
                                    "description": (
                                        "Present and true when content was cut "
                                        "to fit the response budget. Fetch the "
                                        "full body via the memory_id argument."
                                    ),
                                },
                                "content_length": {
                                    "type": "integer",
                                    "description": (
                                        "Original content size in chars (set "
                                        "when truncated)."
                                    ),
                                },
                            },
                        },
                        {
                            "type": "array",
                            "description": (
                                "Tabular row (format=tabular): cells in the "
                                "order named by the ``columns`` header."
                            ),
                        },
                    ],
                },
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Present only when ``format`` is ``tabular``: the field "
                    "names, in order, that each row array in ``memories`` "
                    "carries. Declared once so field names are not repeated "
                    "per memory (issue #170)."
                ),
            },
            "format": {
                "type": "string",
                "enum": ["json", "tabular"],
                "description": (
                    "The encoding applied to ``memories``: ``json`` (array of "
                    "objects, default) or ``tabular`` (array of cell arrays + "
                    "a ``columns`` header). Self-describes the response so a "
                    "client reads rows correctly without guessing."
                ),
            },
            "intent": {
                "type": "string",
                # source: mcp_server/core/query_intent.py::QueryIntent — every
                # value the classifier can emit must be in this enum or MCP
                # output validation rejects the response. Previously the
                # schema was narrower than the classifier's range, so any
                # query falling back to QueryIntent.GENERAL ("general")
                # failed validation. Issue #46.
                "enum": [
                    "temporal",
                    "causal",
                    "semantic",
                    "entity",
                    "knowledge_update",
                    "multi_hop",
                    "instruction",
                    "event_order",
                    "summarization",
                    "preference",
                    "general",
                ],
                "description": (
                    "Classified query intent that drove the signal-weight profile."
                ),
            },
            "count": {"type": "integer", "description": "Number of memories returned."},
            "receipt_id": {
                "type": "integer",
                "description": (
                    "Append-only injection receipt recording exactly the "
                    "memories in this response (blame path, decision "
                    "4255039). Absent when no memory was injected or the "
                    "receipt write failed."
                ),
            },
        },
    },
    "description": (
        "Retrieve memories from the Cortex store using intent-adaptive PG "
        "recall (server-side WRRF fusion of vector + FTS + trigram + heat + "
        "recency) followed by FlashRank cross-encoder reranking and "
        "production enrichments (prospective memory injection, Hebbian "
        "co-activation strengthening, neuro-symbolic rules, strategic ordering "
        "to mitigate Lost-in-the-Middle, Liu et al. 2023). Use this before "
        "any non-trivial work to check what Cortex already knows; running "
        "blind is unacceptable when recall takes ~200ms. Distinct from "
        "`recall_hierarchical` (returns the L0/L1/L2 cluster topology, not "
        "a flat ranked list), `navigate_memory` (graph BFS over co-access "
        "edges from one seed memory), and `get_causal_chain` (entity-graph "
        "traversal, not memory recall). Not read-only: every returned "
        "memory is recorded as a hippocampal replay event — access_count/"
        "replay_count increment and hippocampal_dependency decays (CLS-B, "
        "Ketz et al. 2023) — so repeat calls are not idempotent "
        "(`track_replay_event`, `replay_tracking.py`). Returns ranked "
        "memories with scores, heat, and source."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural-language query describing what to retrieve. Free "
                    "text; intent (temporal/causal/semantic/entity/multi-hop) "
                    "is auto-classified to weight the WRRF signals."
                ),
                "examples": [
                    "why did we choose pgvector over Pinecone?",
                    "failed attempts to fix recall regression",
                    "what does the consolidate handler do?",
                ],
            },
            "domain": {
                "type": "string",
                "description": (
                    "Restrict results to a single cognitive domain. Omit to "
                    "search across all domains."
                ),
                "examples": ["cortex", "auth-service"],
            },
            "directory": {
                "type": "string",
                "description": (
                    "Restrict results to memories tagged with a specific "
                    "absolute project directory."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum number of ranked memories to return after reranking."
                ),
                "default": 10,
                "minimum": 1,
                "maximum": 100,
                "examples": [5, 10, 25],
            },
            "min_heat": {
                "type": "number",
                "description": (
                    "Minimum heat (0.0-1.0) for a memory to be considered. "
                    "Lower = include colder/older memories. Use 0 to include "
                    "everything."
                ),
                "default": 0.05,
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.0, 0.05, 0.3],
            },
            "agent_topic": {
                "type": "string",
                "description": (
                    "Restrict to memories produced under a specific agent "
                    "context tag (subagent topic isolation)."
                ),
                "examples": ["engineer", "researcher", "reviewer"],
            },
            "include_low_signal": {
                "type": "boolean",
                "description": (
                    "When false (default), drops memories tagged as auto-"
                    "captures (``auto-captured``, ``tool:edit``, ``_backfill``, "
                    "``stage-N``, ``session-summary``, …) so curated content "
                    "(ADRs, lessons, conventions) surfaces in the first few "
                    "results. Spike 2026-05-13 showed unfiltered recall is "
                    "drowned by tool-output captures even for queries about "
                    "design decisions. Set true for debugging / replay "
                    "tooling that needs the raw memory feed."
                ),
                "default": False,
            },
            "include_related": {
                "type": "boolean",
                "description": (
                    "When true, inline a one-hop relation walk per recalled "
                    "memory: ``related.versions`` (supersession-chain neighbors "
                    "— the fact this row replaced and the one that replaced it) "
                    "and ``related.entities`` (directly related entities via the "
                    "knowledge graph). A cheap mid-tier enrichment between flat "
                    "recall and the full context assembler. Default false."
                ),
                "default": False,
            },
            "cross_domain": {
                "type": "boolean",
                "description": (
                    "ADR-0054 opt-out for the spreading-activation entity-"
                    "graph expansion stage only (the primary WRRF search "
                    "above stays scoped to ``domain`` regardless of this "
                    "flag). When true, that stage may inject memories from "
                    "OTHER domains reachable through a shared entity (e.g. "
                    "a common function name). Defaults to false: measured "
                    "52.8% cross-domain injection rate when this stage runs "
                    "unscoped. Mirrors the existing ``include_globals`` "
                    "opt-in shape. Orthogonal to ``sa_mode``."
                ),
                "default": False,
            },
            "sa_mode": {
                "type": "string",
                "enum": ["tail", "augment", "off"],
                "default": "tail",
                "description": (
                    "ADR-0054 addendum (2026-07-11 garde x3 bench incident). "
                    "``tail`` (default) only appends spreading-activation "
                    "candidates to fill out a short result list, never "
                    "reordering or rescoring an existing one — benchmark-"
                    "neutral by construction on any corpus dense enough to "
                    "already fill ``max_results``. ``augment`` is the "
                    "pre-fusion mode that can reorder/outrank existing "
                    "candidates — measured to regress LongMemEval MRR "
                    "(0.9166->0.9009) even with domain scoping; kept for "
                    "future dedicated tuning, never the default. ``off`` "
                    "disables the channel."
                ),
            },
            "tags_any": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Positive tag filter (OR): keep only memories that carry "
                    "at least one of the listed tags. Applied after the WRRF "
                    "recall pipeline, at the same stage as the low-signal "
                    'filter. Pass ``tags_any=["archival"]`` to retrieve only '
                    "archival-tier memories."
                ),
                "default": [],
                "examples": [["archival"], ["lesson", "decision"]],
            },
            "tags_all": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Positive tag filter (AND): keep only memories that carry "
                    "ALL of the listed tags. Applied after the WRRF recall "
                    "pipeline, at the same stage as the low-signal filter."
                ),
                "default": [],
                "examples": [["archival", "scope:engineer"]],
            },
            "memory_id": {
                "type": "integer",
                "description": (
                    "Fetch one memory by id, bypassing search. Use to "
                    "retrieve the full content of a result that came back "
                    "with ``truncated: true``. ``query`` is ignored when "
                    "set (still required by the schema; pass the id as a "
                    "string if nothing better)."
                ),
            },
            "content_offset": {
                "type": "integer",
                "description": (
                    "With ``memory_id``: start the returned content at this "
                    "character offset. Page through contents larger than "
                    "the response budget by re-calling with the previous "
                    "offset + the length of the slice received."
                ),
                "default": 0,
                "minimum": 0,
            },
            "format": {
                "type": "string",
                "enum": ["json", "tabular"],
                "description": (
                    "Wire encoding for the ``memories`` list. ``json`` "
                    "(default) returns an array of memory objects. "
                    "``tabular`` declares the field names once in a "
                    "``columns`` header and returns each memory as a cell "
                    "array in that order, which drops the per-item repetition "
                    "of field names on homogeneous result sets (issue #170). "
                    "No information is lost — every field is recoverable by "
                    "column position, and ids stay present for fetch-by-id. "
                    "Applied after the response-budget water-filling, so the "
                    "same budget cap still holds."
                ),
                "default": "json",
            },
        },
    },
}

logger = logging.getLogger(__name__)

_store: MemoryStore | None = None
_momentum_state: dict = {"momentum": 0.5}


def _resolve_session_id() -> str | None:
    """Best-effort session-identity lookup for the T1 receipt (T2-H3).

    precondition: none. postcondition: returns the current window's
    session id, or None on absence/tombstone/pid-divergence (the
    registry's own contract — ``current_window_session`` never raises
    by construction, ``session_registry.py`` docstring) OR on any
    unforeseen exception surfacing from the registry. Recall's primary
    read path must never fail because of a blame-path side channel —
    a bare ``except Exception`` here is the named degradation mode
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


# Below this many results the head/middle/tail reorder is a no-op split.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction (Liu et al. 2023 motivates the
# reorder, not this minimum)
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
    # source: structural — co-activation strengthens pairs of co-retrieved
    # entities, so it needs at least two results
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
    if stored is None:
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
    fmt = parse_format(args.get("format") if args else None)
    if args and args.get("memory_id") is not None:
        return _fetch_by_id(
            int(args["memory_id"]), int(args.get("content_offset") or 0), fmt
        )
    if not args or not args.get("query"):
        # Issue #46: even the early-return must satisfy the outputSchema's
        # required keys (`memories`).
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

    # Low-signal filter (spike 2026-05-13). Tool-output captures,
    # backfilled imports, and stage reports dominate unfiltered recall
    # even for queries about design decisions, drowning out curated
    # ADRs / lessons / conventions. Filter unless the caller opts in.
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
    # The legacy `results`/`total`/`query_intent` aliases byte-duplicated
    # every memory on the wire (measured: 815KB response for 15 memories,
    # 50% pure duplication — 2026-06-09 audit). All consumers now read the
    # schema-aligned keys.
    resp = {
        "memories": results,
        "count": len(results),
        "intent": str(intent),
        "low_signal_dropped": low_signal_dropped,
        "dispatch_tier": "pg",
        "signals": {},
        "enhancements": build_enhancements(query, intent, "pg", settings),
    }
    # Bounded I/O: the host rejects tool results over its token cap
    # (core/response_budget.py docstring for the measured derivation).
    # Truncated items keep their id; full content via the memory_id arg.
    # Bound against the RESERVED budget: the self-describing ``format`` field
    # (and, in tabular mode, the ``columns`` header) is appended after this,
    # so its worst-case cost is held out of the cap here (issue #170).
    resp = bound_payload(
        resp,
        [ListTarget("memories", weight_key="score")],
        reserved_budget(settings.MAX_RESPONSE_CHARS),
    )
    resp["count"] = len(resp["memories"])
    # Blame path T1 (decision 4255039): the receipt is emitted AFTER
    # bound_payload so it mirrors exactly what enters the context
    # (transcript↔DB parity invariant) — entries dropped by the response
    # budget were never injected. T2-D7/T2-H3: session identity is
    # resolved fresh at THIS emission (no cache — the window's session
    # changes under the process across /clear, T2-D7) via the per-window
    # registry (T2-H1). Degrades to None on any registry anomaly (no
    # entry, dead pid, pid-reuse, tombstone, unknown schema) — never a
    # guessed value (design §1 invariant); the recall read path itself
    # never fails on registry errors (current_window_session's contract).
    receipt_id = emit_injection_receipt(
        store, resp["memories"], session_id=_resolve_session_id()
    )
    if receipt_id is not None:
        resp["receipt_id"] = receipt_id
    # Tabular encoding (issue #170): compose AFTER bound_payload's
    # selection/condensation and AFTER the receipt (which needs the memory
    # objects to record ids), re-checking the SAME budget. On homogeneous
    # sets this declares field names once instead of per memory; json is the
    # default escape hatch. Truncated items keep their id in either encoding.
    resp = encode_within_budget(resp, "memories", fmt, settings.MAX_RESPONSE_CHARS)
    return resp


# Telemetry-instrumented public entry. Wrapper records latency, byte
# volume, and result count per call (Popper C6 read/write ratio audit).
handler = instrument("recall", _handler_impl, result_count_key="memories")
