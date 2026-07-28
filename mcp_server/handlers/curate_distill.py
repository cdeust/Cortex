"""Handler: curate_distill — emit understanding-level distillation jobs
the in-session LLM consumes (M-D8).

Composition root for ``core.distillation`` + ``core.distillation_reporting``.
Same role split as ``curate_wiki`` (the only distillation mechanism in this
system that has ever produced anything, audited 2026-07-10): this handler
assembles candidate "dossiers" — pre-existing evidence a lesson-shaped
synthesis is possible — and the in-session LLM authors the WHY as a normal
``remember`` call. This handler is READ-ONLY: it never writes a memory row.

Three dossier kinds (design doc §M-D8):
  1. error_success  — an error-tagged memory paired with the nearest later
     success-tagged memory sharing lexical entities.
  2. co_access_family — a connected component of memories that are both
     individually revisited often (access_count) and were accessed close
     together in time (temporal co-access).
  3. entity_family — a topic-cohesive cluster of memories around a
     dominant entity (reuses ``core.auto_curator.build_clusters`` as-is —
     no second clustering implementation).

Idempotence: each dossier carries a deterministic ``marker`` tag
(``distill-of:<hash>``). Before emitting a job, this handler skips any
dossier whose marker already appears on a stored ``lesson`` memory — the
same skip-before-offer pattern ``memify_derive.py`` uses for
``derived-rel:`` markers. This bounds server-side re-offering; it cannot
force the LLM to include the marker tag when it writes (same trust
boundary ``curate_wiki`` already accepts for ``wiki_write``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.core.auto_curator import (
    MIN_AVG_HEAT_FOR_PAGE,
    MIN_MEMORIES_PER_CLUSTER,
    build_clusters,
)
from mcp_server.core.distillation import (
    build_co_access_dossiers,
    build_error_success_dossiers,
    dossier_from_cluster,
    DistillDossier,
)
from mcp_server.core.distillation_reporting import (
    build_distill_prompt,
    summarize_derived_usage,
)
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)

# Bounded scan sizes — mirrors memify_derive.py's _CANDIDATE_SCAN_LIMIT
# (bounded-I/O convention, audit 2026-06-09).
_TAG_SCAN_LIMIT = 500
_CO_ACCESS_SCAN_LIMIT = 200
_MEMORY_PREVIEW_CAP = 200  # chars, matches navigate_memory's convention

# Reuses core/curation.py::identify_strengtheneable's existing
# `min_access: int = 5` — the system's established "meaningfully
# revisited" threshold — for the co-access dossier's `min_access` filter.
_MIN_RECURRING_ACCESS = 5

schema = {
    "title": "Curate distillation jobs",
    "annotations": READ_ONLY,
    "description": (
        "Auto-distiller: returns structured jobs the in-session LLM "
        "consumes to author understanding-level 'lesson' memories from "
        "PG memory dossiers (error->success pairs, recurring co-access "
        "families, entity-cohesive clusters). Each job carries a "
        "dossier's memory_ids, a marker tag for idempotence, and a "
        "complete prompt naming the required `remember` call shape "
        "(tags=['lesson', <marker>, 'derived-src:<id>', ...], "
        "write_class='deliberate'). The conversational LLM reads each "
        "job, decides whether the sources justify a durable lesson, and "
        "writes it via `remember` — or skips the dossier. No server-side "
        "write happens here. Distinct from `curate_wiki` (wiki PAGES; "
        "this is memory-level LESSONS) and `consolidate`'s `memify` "
        "stage (memify_derive synthesizes templated inventory facts "
        "server-side with no LLM judgment; this delegates judgment to "
        "the LLM, per M-D8). Also returns `memify_derive_usage`: a "
        "read-only snapshot (count/access/useful) of memify_derive's "
        "existing 'derived'-tagged output, for the 30-day keep/retire "
        "measurement M-D8 requires. Read-only. Latency ~200-500ms. "
        "Returns {jobs: [{job_type, dossier_kind, memory_ids, marker, "
        "prompt}], total_dossiers_eligible, memify_derive_usage, "
        "instructions}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Restrict entity_family dossiers to a single domain. "
                    "error_success and co_access_family dossiers are "
                    "corpus-wide (their pairing signal is entity/time, "
                    "not domain)."
                ),
                "examples": ["cortex", "agentic-ai"],
            },
            "limit": {
                "type": "integer",
                "default": 5,
                "minimum": 1,
                "maximum": 30,
                "description": "Maximum total jobs to return across all dossier kinds.",
            },
            "window_hours": {
                "type": "number",
                "default": 168.0,
                "minimum": 1.0,
                "maximum": 720.0,
                "description": (
                    "Search cap for error->success pairing. Default 168h "
                    "(7 days) reuses navigate_memory's existing maximum "
                    "co-access window as the search bound, not a new "
                    "invented constant."
                ),
            },
            "include_error_success": {"type": "boolean", "default": True},
            "include_co_access": {"type": "boolean", "default": True},
            "include_entity_family": {"type": "boolean", "default": True},
            "min_memories": {
                "type": "integer",
                "default": MIN_MEMORIES_PER_CLUSTER,
                "description": "Minimum memories per entity_family cluster.",
            },
            "min_avg_heat": {
                "type": "number",
                "default": MIN_AVG_HEAT_FOR_PAGE,
                "description": "Minimum average heat for an entity_family cluster.",
            },
            "memory_pool_size": {
                "type": "integer",
                "default": 500,
                "description": "Pool size drawn for entity_family clustering.",
            },
        },
    },
}


def _get_store():
    return get_shared_store()


def _tags_of(mem: dict[str, Any]) -> list[str]:
    tags = mem.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    return [str(t) for t in tags]


def _existing_distill_markers(store: Any) -> set[str]:
    """Every ``distill-of:...`` marker already present on a stored
    ``lesson`` memory. Degrades to the empty set on any failure — never
    blocks job emission, mirrors
    ``memify_derive._existing_derived_markers``'s posture, but records
    the failure via `observability.silent_failure` instead of a silent
    bare except (audit 2026-07-11)."""
    if not hasattr(store, "get_memories_by_tag"):
        return set()
    try:
        mems = store.get_memories_by_tag("lesson", limit=_TAG_SCAN_LIMIT)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("curate_distill.existing_markers")
        silent_failure.note("curate_distill.existing_markers", exc)
        return set()
    return {
        tag for mem in mems for tag in _tags_of(mem) if tag.startswith("distill-of:")
    }


def _fetch_tag_pool(store: Any, tag: str) -> list[dict[str, Any]]:
    if not hasattr(store, "get_memories_by_tag"):
        return []
    try:
        return store.get_memories_by_tag(tag, limit=_TAG_SCAN_LIMIT)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("component")
        silent_failure.note(f"curate_distill.fetch_tag_pool.{tag}", exc)
        return []


def _fetch_co_access_pairs(store: Any) -> list[tuple[int, int, float]]:
    if not hasattr(store, "get_temporal_co_access"):
        return []
    try:
        return store.get_temporal_co_access(
            window_hours=2.0,
            min_access=_MIN_RECURRING_ACCESS,
            limit=_CO_ACCESS_SCAN_LIMIT,
        )
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("curate_distill.fetch_co_access_pairs")
        silent_failure.note("curate_distill.fetch_co_access_pairs", exc)
        return []


def _fetch_memory_previews(
    store: Any, memory_ids: list[int], cache: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Bounded lookup of {id, content, tags} for a dossier's members,
    reusing already-fetched dicts in ``cache`` before hitting the store."""
    previews = []
    for mid in memory_ids:
        mem = cache.get(mid)
        if mem is None:
            try:
                mem = store.get_memory(mid)
            except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("curate_distill.fetch_memory_preview")
                silent_failure.note("curate_distill.fetch_memory_preview", exc)
                mem = None
            if mem:
                cache[mid] = mem
        if mem:
            previews.append(
                {
                    "id": mid,
                    "content": mem.get("content", "")[:_MEMORY_PREVIEW_CAP],
                    "tags": mem.get("tags", []),
                }
            )
    return previews


def _serialise_job(
    dossier: DistillDossier, previews: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "job_type": "distill",
        "dossier_kind": dossier.kind,
        "topic": dossier.topic,
        "domain": dossier.domain,
        "memory_ids": dossier.memory_ids,
        "marker": dossier.marker,
        "avg_heat": round(dossier.avg_heat, 3),
        "prompt": build_distill_prompt(dossier, previews),
    }


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble distillation dossiers and the memify_derive usage snapshot.

    Precondition: none (all inputs optional; degrades gracefully when the
    store lacks tag/co-access support, e.g. SQLite fallback in tests).
    Postcondition: read-only — no memory row is created, updated, or
    tagged by this handler. `jobs` is capped at `limit`, entries already
    covered by an existing `distill-of:` marker are excluded.
    """
    # `or <default>` would silently discard an intentional falsy value
    # (0, 0.0, "") — e.g. `min_avg_heat=0.0` (a legitimate "accept any
    # heat" request) would otherwise be overwritten by
    # MIN_AVG_HEAT_FOR_PAGE. Every numeric/string arg below is resolved
    # via an explicit `is None` check instead (caught by
    # test_entity_family_dossier_surfaced's `min_avg_heat=0.0` case).
    args = args or {}
    domain = args.get("domain") or None
    limit = args.get("limit")
    limit = 5 if limit is None else int(limit)
    window_hours = args.get("window_hours")
    window_hours = 168.0 if window_hours is None else float(window_hours)
    include_error_success = bool(args.get("include_error_success", True))
    include_co_access = bool(args.get("include_co_access", True))
    include_entity_family = bool(args.get("include_entity_family", True))
    min_memories = args.get("min_memories")
    min_memories = (
        MIN_MEMORIES_PER_CLUSTER if min_memories is None else int(min_memories)
    )
    min_avg_heat = args.get("min_avg_heat")
    min_avg_heat = (
        MIN_AVG_HEAT_FOR_PAGE if min_avg_heat is None else float(min_avg_heat)
    )
    memory_pool_size = args.get("memory_pool_size")
    memory_pool_size = 500 if memory_pool_size is None else int(memory_pool_size)

    store = _get_store()
    existing_markers = _existing_distill_markers(store)
    mem_cache: dict[int, dict[str, Any]] = {}

    dossiers: list[DistillDossier] = []
    counts_by_kind: dict[str, int] = {}

    if include_error_success:
        errors = _fetch_tag_pool(store, "error")
        successes = _fetch_tag_pool(store, "success")
        for m in errors + successes:
            if m.get("id") is not None:
                mem_cache[m["id"]] = m
        es = build_error_success_dossiers(errors, successes, window_hours=window_hours)
        counts_by_kind["error_success"] = len(es)
        dossiers.extend(es)

    if include_co_access:
        pairs = _fetch_co_access_pairs(store)
        ids = {i for a, b, _ in pairs for i in (a, b)}
        heat_by_id: dict[int, float] = {}
        for mid in ids:
            mem = mem_cache.get(mid)
            if mem is None:
                try:
                    mem = store.get_memory(mid)
                except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("curate_distill.co_access_heat_lookup")
                    silent_failure.note("curate_distill.co_access_heat_lookup", exc)
                    mem = None
                if mem:
                    mem_cache[mid] = mem
            if mem:
                heat_by_id[mid] = mem.get("effective_heat", mem.get("heat", 0.0))
        ca = build_co_access_dossiers(pairs, heat_by_id=heat_by_id)
        # topic backfill: dominant entity from the highest-heat member's content
        for d in ca:
            top = max(d.memory_ids, key=lambda i: heat_by_id.get(i, 0.0), default=None)
            top_mem = mem_cache.get(top) if top is not None else None
            if top_mem:
                d.topic = (top_mem.get("content") or "")[:40].strip() or "untitled"
                d.domain = top_mem.get("domain", "")
        counts_by_kind["co_access_family"] = len(ca)
        dossiers.extend(ca)

    if include_entity_family:
        mems = store.get_recently_accessed_memories(
            limit=memory_pool_size, heads_only=True
        )
        if len(mems) < min_memories * 2:
            mems = store.get_recent_memories(limit=memory_pool_size)
        for m in mems:
            if m.get("id") is not None:
                mem_cache[m["id"]] = m
        clusters = build_clusters(
            mems,
            domain=domain,
            min_memories=min_memories,
            min_avg_heat=min_avg_heat,
            skip_recently_authored=False,
        )
        ef = [dossier_from_cluster(c) for c in clusters]
        counts_by_kind["entity_family"] = len(ef)
        dossiers.extend(ef)

    total_eligible = len(dossiers)
    dossiers = [d for d in dossiers if d.marker not in existing_markers]
    already_distilled = total_eligible - len(dossiers)

    jobs = []
    for dossier in dossiers[:limit]:
        previews = _fetch_memory_previews(store, dossier.memory_ids, mem_cache)
        if not previews:
            continue
        jobs.append(_serialise_job(dossier, previews))

    derived_usage = summarize_derived_usage(_fetch_tag_pool(store, "derived"))

    return {
        "jobs": jobs,
        "returned": len(jobs),
        "total_dossiers_eligible": total_eligible,
        "already_distilled_skipped": already_distilled,
        "counts_by_kind": counts_by_kind,
        "memify_derive_usage": derived_usage,
        "domain_filter": domain or "(all)",
        "instructions": _instructions_for_llm(len(jobs), total_eligible),
    }


def _instructions_for_llm(n_jobs: int, n_eligible: int) -> str:
    if n_jobs == 0:
        return (
            f"No distillation jobs returned ({n_eligible} dossiers were "
            "eligible before dedup/limit). Relax min_memories/min_avg_heat, "
            "widen window_hours, or check that error/success-tagged "
            "memories exist."
        )
    return (
        f"{n_jobs} distillation job(s) returned, out of {n_eligible} "
        "eligible dossiers. For each job: read `prompt`, decide whether "
        "the sources justify a durable lesson (root cause, rule, or "
        "decision + rationale — not a restatement of events), and if so "
        "call `remember` exactly as the prompt specifies (tags include "
        "the job's `marker` for idempotence and one `derived-src:<id>` "
        "per source for provenance, write_class='deliberate'). Skip "
        "dossiers that don't clear that bar — a distillation job is a "
        "candidate, not a mandate. Call `curate_distill` again once this "
        "batch is processed."
    )
