"""MCP tool schema for `remember` — extracted from remember.py (§4.1
500-line cap; the schema dict is pure data, no logic, so this split is
mechanical: no behavior change).

remember.py imports `schema` from here as the module-level export the
MCP server registration reads.
"""

from __future__ import annotations

from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE

schema = {
    "title": "Remember (store a memory)",
    "annotations": IDEMPOTENT_WRITE,
    "outputSchema": {
        "type": "object",
        "required": ["stored", "action"],
        "properties": {
            "stored": {
                "type": "boolean",
                "description": (
                    "True if content landed in the memory store (as new row or a merge "
                    "into an existing one)."
                ),
            },
            "memory_id": {
                "type": "integer",
                "description": (
                    "ID of the resulting memory row (PG bigint). Present when "
                    "stored=true."
                ),
            },
            "action": {
                "type": "string",
                "enum": [
                    "stored",
                    "merged",
                    "rejected",
                    "superseded",
                    "superseded_conflict",
                ],
                "description": (
                    "stored=new row; merged=folded into the most-similar existing "
                    "memory; rejected=redundant per the predictive-coding gate; "
                    "superseded=new row replaces an older version (append-only edge "
                    "posted); superseded_conflict=another writer superseded the target "
                    "first — nothing was kept, rebase and retry."
                ),
            },
            "reason": {
                "type": "string",
                "description": (
                    "Human-readable explanation of the gate decision (e.g. 'low "
                    "surprise', 'high entity overlap')."
                ),
            },
            "merged_with": {
                "type": "integer",
                "description": (
                    "ID of the existing memory (PG bigint) when action=merged."
                ),
            },
            "superseded_id": {
                "type": "integer",
                "description": "ID of the replaced memory when action=superseded.",
            },
            "supersede_target_id": {
                "type": "integer",
                "description": (
                    "Requested supersession target when the supersede path rejected or "
                    "conflicted."
                ),
            },
            "current_superseded_by_id": {
                "type": ["integer", "null"],
                "description": (
                    "The version that currently supersedes the target (present on "
                    "supersede rejection/conflict so the caller can rebase)."
                ),
            },
            "heat": {
                "type": "number",
                "description": "Final heat assigned to the new/merged memory.",
            },
            "write_class": {
                "type": "string",
                "enum": ["auto", "deliberate", "derived", "mechanical"],
                "description": (
                    "The write class actually persisted — the explicit "
                    "argument if provided, otherwise the source-based "
                    "fallback default ('deliberate'). Present when "
                    "action=stored|superseded."
                ),
            },
            "provenance": {
                "type": "object",
                "description": (
                    "Write-time provenance feedback (M-D5): grade in "
                    "{verified, verifiable, unverifiable} computed from "
                    "LOCAL-ONLY checks (file existence, git commit lookup, "
                    "artifact digest — no network) on this content's "
                    "checkable references. Never a blocking gate — a "
                    "testimony-only write is still stored. Present when "
                    "action=stored|superseded; persisted as an additive "
                    "`prov:<grade>` tag on the row (never into "
                    "source_attribution — validate_memory.py's grade "
                    "vocabulary there, I6-D6, has exactly one writer). "
                    "Re-graded with network-verified checks (URLs included) "
                    "by the periodic `validate_memory` sweep."
                ),
                "properties": {
                    "grade": {
                        "type": "string",
                        "enum": ["verified", "verifiable", "unverifiable"],
                    },
                    "checkable_refs": {
                        "type": "object",
                        "description": (
                            "Count per reference type: file, commit, url, artifact, "
                            "citation."
                        ),
                    },
                    "hint": {
                        "type": "string",
                        "description": (
                            "Human-readable nudge — what to add for a higher grade."
                        ),
                    },
                },
            },
        },
    },
    "description": (
        "Store a memory through the flat 4-signal predictive-coding write "
        "gate (embedding, entity, temporal, and structural novelty — "
        "Friston-inspired prediction-error gating). Novel surprising "
        "content passes; "
        "redundant content is rejected or merged with the most-similar "
        "existing memory via active curation. After write: thermodynamic "
        "tagging, knowledge-graph entity extraction, neuromodulation "
        "(DA/NE/ACh/5-HT), engram allocation. FOR A DURABLE CLAIM (a "
        "fact, decision, or lesson meant to outlive this session), include "
        "a checkable reference in `content` — a file path, a git commit "
        "SHA, a URL, or a content-addressed artifact digest — so it can "
        "grade above 'unverifiable' (see the `provenance` response field "
        "and coding-standards.md §8, 'no source, no implementation'); "
        "testimony without one is still stored, just graded accordingly. "
        "Use this after any non-trivial discovery, fix, decision, or "
        "lesson — if it would surprise a future session, store it. "
        "Distinct from `anchor` (pins an EXISTING memory, doesn't create), "
        "`wiki_write` (creates an .md page, not a memory row), "
        "`validate_memory` (re-grades EXISTING memories with network-"
        "verified checks, not a write path), and `add_rule` (recall-time "
        "filter, not stored content). Mutates memories + entities + "
        "relationships tables. Latency ~50-100ms. Returns {stored, "
        "memory_id, action: stored|merged|rejected, reason, provenance}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["content"],
        "properties": {
            "content": {
                "type": "string",
                "description": (
                    "The memory content to store. Plain prose works; markdown "
                    "is preserved. Aim for a single fact, decision, or lesson "
                    "with enough context to be intelligible standalone."
                ),
                "examples": [
                    "Recall regression on 2026-03-12 traced to FlashRank ONNX cache; "
                    "clearing fixed it.",
                    "Decided to use pgvector HNSW (m=16, ef_construction=64) for ANN — "
                    "3x faster than IVFFlat.",
                ],
            },
            "tags": {
                "type": "array",
                "description": (
                    "Free-form tags for filtering and rules. Convention: use "
                    "lowercase, hyphenated, and include at least one category "
                    "(e.g., 'bug-fix', 'decision', 'lesson')."
                ),
                "items": {"type": "string"},
                "default": [],
                "examples": [["bug-fix", "recall"], ["decision", "embeddings"]],
            },
            "directory": {
                "type": "string",
                "description": (
                    "Absolute project directory the memory belongs to. Defaults "
                    "to the current working directory; resolved against git-root "
                    "for stable domain mapping."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
            "domain": {
                "type": "string",
                "description": (
                    "Cognitive-domain override. Auto-detected from directory if "
                    "omitted; only set this when crossing project boundaries."
                ),
                "examples": ["cortex", "ai-architect"],
            },
            "source": {
                "type": "string",
                "description": "Origin tag for provenance and replay scoring.",
                # source:
                # mcp_server/core/distillation_reporting.py::build_distill_prompt
                # is the sole emitter of source='distillation' (grep-verified,
                # 2026-07-12) — the required-call-shape prompt for M-D8
                # distillation dossiers. classify_write_class (core/write_class.py)
                # does not special-case it (not in _DERIVED_SOURCES/
                # _MECHANICAL_SOURCES prefixes/sets), so an unclassified
                # 'distillation' source falls through to DELIBERATE by default —
                # matching the prompt's own explicit write_class='deliberate'.
                # Safe to enumerate: no downstream `source ==`/`source in`
                # branch treats it specially (grep-verified).
                "enum": [
                    "session",
                    "tool",
                    "user",
                    "consolidation",
                    "import",
                    "distillation",
                ],
                "default": "user",
                "examples": ["session", "tool"],
            },
            "write_class": {
                "type": "string",
                "description": (
                    "Explicit write class — the caller states what kind of "
                    "write this is; no source-string inference happens when "
                    "this is set (M-D2). One of: "
                    "'auto' (unattended tool-output capture — subject to the "
                    "standard novelty gate AND homeostatic heat regulation; "
                    "this is the ONLY class ever folded/re-suppressed toward "
                    "the domain heat target); "
                    "'deliberate' (a considered, user- or agent-authored "
                    "fact, decision, or lesson — NEVER rejected by the gate "
                    "for low novelty and NEVER heat-folded; near-duplicates "
                    "are still merged/linked/superseded by curation, so "
                    "redundancy is handled without risking silent loss of a "
                    "considered write); "
                    "'derived' (machine-synthesized from an existing corpus "
                    "— consolidation/memify, CLS semantic promotion, sleep-"
                    "compute auto-narration — judged by idempotence markers "
                    "instead of the novelty gate); "
                    "'mechanical' (one-shot bulk import or structural "
                    "indexing — backfill, ingest_*, seed_*, codebase_analyze, "
                    "wiki pointer sync — bypasses the gate entirely, "
                    "force=true semantics). "
                    "Omit to default to 'deliberate' via source-based "
                    "fallback classification (safe default — an "
                    "unclassified write is never assumed to be noise). "
                    "An unrecognized value is rejected with a "
                    "ValidationError, never silently reinterpreted."
                ),
                "enum": ["auto", "deliberate", "derived", "mechanical"],
                "examples": ["deliberate", "auto"],
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Bypass the predictive-coding write gate and always insert. "
                    "Use sparingly — anchored facts and curated lessons only. "
                    "Combined with supersedes_id this is the sovereign human "
                    "correction: the gate is bypassed but the supersession "
                    "edge is still posted."
                ),
                "default": False,
            },
            "supersedes_id": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "ID of the memory this content replaces (append-only "
                    "correction). A new row is inserted, the target's "
                    "superseded_by_id is compare-and-set to it, and recall "
                    "demotes the old version. Rejected when the target is "
                    "missing or already superseded — an existing version "
                    "chain is never forked silently. Bypasses automatic "
                    "curation (the intent is explicit); the write gate "
                    "still applies unless force=true."
                ),
                "examples": [4255039],
            },
            "agent_topic": {
                "type": "string",
                "description": (
                    "Subagent context tag for topic isolation; recall can scope "
                    "to a single agent persona."
                ),
                "examples": ["engineer", "researcher", "reviewer"],
            },
            "is_global": {
                "type": "boolean",
                "description": (
                    "If true, the memory is visible across all projects/domains. "
                    "Use for genuinely global facts (e.g., user identity, "
                    "operating principles)."
                ),
                "default": False,
            },
            "created_at": {
                "type": "string",
                "description": (
                    "Original ISO-8601 timestamp for imported/backfilled memories. "
                    "Omit for live captures (server timestamps the row)."
                ),
                "format": "date-time",
                "examples": ["2026-04-14T10:23:00Z"],
            },
            "initial_heat": {
                "type": "number",
                "description": (
                    "Initial heat override [0.0, 1.0] used by backfill and "
                    "import paths to reflect historical memory age. Defaults "
                    "to 1.0 for live writes. Surprise boost still applies on "
                    "top. Setting this below 1.0 keeps old memories out of "
                    "the hot cohort so homeostatic scaling can rebalance "
                    "the distribution (issue #14 P1)."
                ),
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 1.0,
                "examples": [0.3, 0.65, 0.88, 1.0],
            },
        },
    },
}
