"""Recall tool contract (split from recall.py for issue #706)."""

from mcp_server.handlers.decision_recall import SCOPE_PROPERTIES
from mcp_server.handlers._tool_meta import NON_IDEMPOTENT_WRITE

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
                    # source: ADR-0430
                    "Ranked list of matching memories. Best result is index 0. With "
                    '``format: "json"`` (default) each element is a memory object; '
                    'with ``format: "tabular"`` each element is a cell array whose '
                    "fields are named once in the sibling ``columns`` header."
                ),
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": (
                                        "Memory UUID or wiki:ADR-NNNN identity."
                                    ),
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
                                "capture_origin": {
                                    "type": "string",
                                    "description": (
                                        "Capture channel: deliberate, local_action, "
                                        "network, unknown or legacy."
                                    ),
                                },
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
                    # source: ADR-0430
                    "Present only when ``format`` is ``tabular``: the field names, in "
                    "order, that each row array in ``memories`` carries. Declared "
                    "once so field names are not repeated per memory."
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
                # source: ADR-0430
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
            "low_signal_dropped": {
                "type": "integer",
                "description": (
                    "System captures hidden from the retrieved candidate set."
                ),
            },
            "receipt_id": {
                "type": "integer",
                "description": (
                    "Append-only injection receipt recording exactly the "
                    "memories in this response. Absent when no memory "
                    "was injected or the "
                    "receipt write failed."
                ),
            },
        },
    },
    "description": (
        "Retrieve memories from the Cortex store using intent-adaptive PG "
        "recall (server-side fusion of vector + FTS + trigram + heat + recency: "
        "a weighted sum on PostgreSQL, rank-based WRRF on SQLite) followed "
        "by FlashRank cross-encoder reranking and "
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
        "memories with scores, heat, and source. Bare ADR-NNNN queries "
        "resolve the canonical wiki page before semantic retrieval; project_root "
        "explicitly selects a tracked project wiki. Page longer decisions with "
        "the same query and content_offset."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            **SCOPE_PROPERTIES,
            "query": {
                "type": "string",
                "description": (
                    "Natural-language query describing what to retrieve. Free "
                    "text; intent (temporal/causal/semantic/entity/multi-hop) "
                    "is auto-classified to weight the fusion signals."
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
                    # source: ADR-0430
                    "When false (default), hides system captures identified by "
                    "capture_origin (local_action or network) and reports their "
                    "count in low_signal_dropped. User tags never hide memories. "
                    "Set true to include captures with their capture_origin label."
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
                    # source: ADR-0430
                    "Opt in to cross-domain memories in the spreading-activation "
                    "entity-graph expansion stage only. The primary fused search "
                    "remains scoped to ``domain``. When true, expansion may inject "
                    "memories from other domains reachable through shared entities. "
                    "Defaults to false. Orthogonal to ``sa_mode``."
                ),
                "default": False,
            },
            "sa_mode": {
                "type": "string",
                "enum": ["tail", "augment", "off"],
                "default": "tail",
                "description": (
                    # source: ADR-0430
                    "``tail`` (default) appends spreading-activation candidates only "
                    "when the result list is shorter than ``max_results``, without "
                    "reordering or rescoring existing results. ``augment`` applies "
                    "expansion before fusion and can reorder existing candidates. "
                    "``off`` disables the channel."
                ),
            },
            "tags_any": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Positive tag filter (OR): keep only memories that carry "
                    "at least one of the listed tags. Applied after the fused "
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
                    "ALL of the listed tags. Applied after the fused recall "
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
                    # source: ADR-0430
                    "Wire encoding for the ``memories`` list. ``json`` (default) "
                    "returns an array of memory objects. ``tabular`` declares the "
                    "field names once in a ``columns`` header and returns each memory "
                    "as a cell array in that order, which drops the per-item "
                    "repetition of field names on homogeneous result sets. No "
                    "information is lost — every field is recoverable by column "
                    "position, and ids stay present for fetch-by-id. Applied after "
                    "the response-budget water-filling, so the same budget cap still "
                    "holds."
                ),
                "default": "json",
            },
        },
    },
}

