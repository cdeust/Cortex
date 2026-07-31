"""Handler: curate_wiki — emit authoring jobs the in-session LLM consumes.

Composition root for the auto-curator (``mcp_server.core.auto_curator``).

Architecture — why this returns jobs instead of authoring directly:

The user's Claude Code session is itself the authoring LLM (Opus 4.7).
Rather than calling an external Anthropic API with a separate key (the
key is the user's session and exposing it via env is fragile), this
handler returns **structured authoring jobs** — clusters of PG memories
paired with the structured prompt the LLM should consume. The in-session
LLM reads the jobs, authors each page in turn, and writes them via
``wiki_write``.

That means the auto-curator's "auto" property comes from two things:

  1. The clustering and prompt-construction work happens without a human
     deciding what to document — ``curate_wiki`` fetches recent
     high-heat clusters, derives topics, and constructs prompts that
     embed all the wiki conventions.

  2. The trigger is automatic — ``consolidate`` runs the same job-
     enqueueing logic on its periodic cycle; SessionStart surfaces
     pending curations to the in-session LLM. The user never asks for
     a specific page; the system notices what deserves documentation
     and proposes it.

The user directive this satisfies:
  > "ALL ACTIONS SHOULD DOCUMENTED BY OPUS 4.7, IT'S NOT POSSIBLE THE
  > LLM IS NOT ABLE TO PRODUCE A DOCUMENTATION FROM AN ACCESS."
  > "The documentation you created now, should be auto created and auto
  > curated."
  > "the anthropic key should be using the user session"
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.core.auto_curator import (
    MIN_AVG_HEAT_FOR_PAGE,
    MIN_MEMORIES_PER_CLUSTER,
    build_clusters,
    build_coverage_jobs,
    build_jobs,
    build_reauthor_jobs,
    sort_coverage_jobs,
)
from mcp_server.core.wiki_coverage import (
    _project_source_root,
    audit_all_domains,
    domain_coverage_covered_count,
    domain_coverage_coverage_ratio,
    domain_coverage_missing_count,
    domain_coverage_missing_scopes,
)
from mcp_server.core.wiki_drift import audit_wiki_drift
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.handlers.curate_wiki_serialize import (
    instructions_for_llm,
    serialise_coverage_job,
    serialise_job,
    serialise_reauthor_job,
)
from mcp_server.handlers.curate_wiki_uncited import report_uncited_deliberate
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.infrastructure.wiki_page_fs import build_wiki_page_port


schema = {
    "title": "Curate wiki",
    "annotations": READ_ONLY,
    "description": (
        "Auto-curator: returns structured authoring jobs the in-session "
        "LLM (Opus 4.7) consumes to author curated wiki pages from PG "
        "memory clusters. Each job carries one cluster's memories, the "
        "suggested wiki path, a list of existing related pages for "
        "cross-linking, and a complete structured prompt that encodes "
        "the wiki documentation conventions (frontmatter, lead, "
        "diagrams, 'why this not the alternatives', 'what can go "
        "wrong', 'see also', primary sources). The conversational LLM "
        "reads each job, authors the page in Markdown, and writes it "
        "via `wiki_write`. No external Anthropic API key required — "
        "the user's existing Claude Code session is the authoring LLM. "
        "Distinct from `wiki_write` (the writer; this is the planner), "
        "`narrative` (one summary; this is N pages), and `consolidate` "
        "(memory maintenance; this is documentation production). "
        "Read-only with respect to PG and wiki. Latency ~300ms for "
        "k=5 jobs. Returns {jobs: [{cluster, prompt, suggested_path, "
        "related_pages}], total_clusters_eligible, instructions}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Restrict curation to a single domain. Omit to "
                    "curate across all domains (sorted by cluster "
                    "value)."
                ),
                "examples": ["cortex", "agentic-ai"],
            },
            "limit": {
                "type": "integer",
                "default": 3,
                "minimum": 1,
                "maximum": 20,
                "description": (
                    "Maximum number of authoring jobs to return. "
                    "Higher = more pages to author per invocation; "
                    "lower = focus on the highest-value clusters."
                ),
            },
            "min_memories": {
                "type": "integer",
                "default": MIN_MEMORIES_PER_CLUSTER,
                "description": (
                    "Minimum memories per cluster to earn a page. "
                    "Below this, a topic doesn't have enough signal."
                ),
            },
            "min_avg_heat": {
                "type": "number",
                "default": MIN_AVG_HEAT_FOR_PAGE,
                "description": (
                    "Minimum average effective_heat of cluster "
                    "memories. Cold clusters yield stale pages."
                ),
            },
            "recent_only": {
                "type": "boolean",
                "default": True,
                "description": (
                    "If true, only consider recently-accessed memories. "
                    "If false, scan the full corpus (slower)."
                ),
            },
            "memory_pool_size": {
                "type": "integer",
                "default": 500,
                "description": (
                    "Number of memories to draw from before clustering. "
                    "Higher = better topic coverage, more compute."
                ),
            },
            "include_coverage": {
                "type": "boolean",
                "default": True,
                "description": (
                    "If true, prepend coverage-driven jobs (missing "
                    "architecture / services / api / data-flow / "
                    "operations pages per project) ahead of cluster-"
                    "driven jobs. Structural scopes get authored "
                    "before heat clusters so a cold reader can navigate "
                    "the wiki end-to-end."
                ),
            },
            "coverage_jobs_max": {
                "type": "integer",
                "default": 4,
                "minimum": 0,
                "maximum": 20,
                "description": (
                    "Cap on how many coverage jobs to return per "
                    "invocation. Coverage gaps can be large on a fresh "
                    "wiki; this prevents one call from monopolising "
                    "the LLM's attention with structural pages."
                ),
            },
            "include_reauthor": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Mix in re-authoring jobs for existing pages whose "
                    "linked source files have moved, whose content is "
                    "older than the freshness window, or whose body "
                    "is off-template. Legacy pages get the same "
                    "detailed treatment as new pages — refined, "
                    "verified, and updated automatically."
                ),
            },
            "reauthor_jobs_max": {
                "type": "integer",
                "default": 3,
                "minimum": 0,
                "maximum": 20,
                "description": (
                    "Cap on how many re-authoring jobs to return per "
                    "invocation. Drift backlog can be large; this "
                    "keeps each batch tractable for the LLM."
                ),
            },
            "report_uncited_deliberate": {
                "type": "boolean",
                "default": False,
                "description": (
                    "I6-D7 reverse loop: when true, SKIP job generation "
                    "entirely and instead return a read-only report of "
                    "active, deliberate (non-auto-captured), verifiably-"
                    "important memories that have zero wiki.citations "
                    "rows — candidates for documentation, not pages "
                    "written for you. Never writes anything (no page, "
                    "no citation, no job)."
                ),
            },
            "uncited_deliberate_limit": {
                "type": "integer",
                "default": 20,
                "minimum": 1,
                "maximum": 200,
                "description": (
                    "Max candidates returned by report_uncited_deliberate=true."
                ),
            },
        },
    },
}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _scan_existing_pages(wiki_root: Path) -> dict[str, list[str]]:
    """Build a topic→[paths] index of existing wiki pages.

    The auto-curator uses this to suggest cross-links via ``[[wiki/path]]``
    notation in the authoring prompt. Topics are derived from the page
    path's slug (last component, minus extension).
    """
    index: dict[str, list[str]] = {}
    if not wiki_root.is_dir():
        return index
    for md_path in wiki_root.rglob("*.md"):
        rel = md_path.relative_to(wiki_root)
        parts = rel.parts
        if not parts or parts[0].startswith((".", "_")):
            continue
        slug = md_path.stem
        # Drop common ID prefixes like "305772-" so the topic is the
        # human-readable part of the slug
        slug = re.sub(r"^\d+-", "", slug)
        # Normalise "decision-" / "lesson-" / "convention-" prefixes
        slug = re.sub(r"^(decision|lesson|convention|spec|reference)-", "", slug)
        # Strip trailing common words ("md")
        slug = slug.replace("-md", "")
        # Use the slug itself as the topic key (lowercased)
        topic = slug.lower()
        path_str = str(rel).replace(".md", "")
        index.setdefault(topic, []).append(path_str)
    return index


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build authoring jobs from PG memory clusters + coverage gaps.

    Two job sources are merged into a single ordered list:

      1. **Coverage jobs** (structural): per-project scope audit. Any
         domain missing an architecture / services / api / data-flow /
         operations / decisions page yields a coverage job. These come
         first because a reader needs the structural anchor pages
         before topic-specific pages make sense.

      2. **Cluster jobs** (empirical): topic-cohesive memory clusters
         that earn a page based on size and heat. These document what
         the user actually worked on.
    """
    args = args or {}

    if bool(args.get("report_uncited_deliberate", False)):
        return report_uncited_deliberate(
            int(args.get("uncited_deliberate_limit") or 20)
        )

    domain = args.get("domain") or None
    limit = int(args.get("limit") or 3)
    min_memories = int(args.get("min_memories") or MIN_MEMORIES_PER_CLUSTER)
    min_avg_heat = float(args.get("min_avg_heat") or MIN_AVG_HEAT_FOR_PAGE)
    recent_only = bool(args.get("recent_only", True))
    memory_pool_size = int(args.get("memory_pool_size") or 500)
    include_coverage = bool(args.get("include_coverage", True))
    coverage_jobs_max = int(args.get("coverage_jobs_max") or 4)
    include_reauthor = bool(args.get("include_reauthor", True))
    reauthor_jobs_max = int(args.get("reauthor_jobs_max") or 3)

    store = get_shared_store()
    # Draw a memory pool. Recently-accessed memories are higher-signal
    # candidates because they reflect what the user actively works on.
    if recent_only:
        # heads_only: wiki pages are authored from memory content —
        # supersession chain heads only.
        memories = store.get_recently_accessed_memories(
            limit=memory_pool_size, heads_only=True
        )
        if len(memories) < min_memories * 2:
            # Fall back to the recent-by-creation pool when access is
            # thin (e.g. fresh DB).
            memories = store.get_recent_memories(limit=memory_pool_size)
    else:
        memories = store.get_recent_memories(limit=memory_pool_size)

    existing_pages = _scan_existing_pages(Path(WIKI_ROOT))
    today = _today()
    # Composition-root wiring (§5.2): core declares WikiPagePort, this
    # handler builds the concrete os/pathlib-backed adapter (issue #314).
    wiki_page_port = build_wiki_page_port(str(WIKI_ROOT))

    # 1. Coverage jobs — top-down structural scopes.
    coverage_payload: list[dict[str, Any]] = []
    domain_coverages_summary: list[dict[str, Any]] = []
    if include_coverage and coverage_jobs_max > 0:
        coverages = audit_all_domains(str(WIKI_ROOT))
        if domain:
            coverages = [c for c in coverages if c.domain == domain]
        # Group recent memories by domain so each coverage job has
        # supporting context to ground the page in.
        mems_by_domain: dict[str, list[dict]] = {}
        for m in memories:
            d = (m.get("domain") or "").lower()
            if d:
                mems_by_domain.setdefault(d, []).append(m)
        coverage_jobs = sort_coverage_jobs(
            build_coverage_jobs(
                coverages,
                existing_pages_by_topic=existing_pages,
                supporting_memories_by_domain=mems_by_domain,
                today=today,
            )
        )
        coverage_payload = [
            serialise_coverage_job(j) for j in coverage_jobs[:coverage_jobs_max]
        ]
        domain_coverages_summary = [
            {
                "domain": c.domain,
                "covered": domain_coverage_covered_count(c),
                "missing": domain_coverage_missing_count(c),
                "coverage_ratio": round(domain_coverage_coverage_ratio(c), 3),
                "missing_scopes": [
                    s.scope.name for s in domain_coverage_missing_scopes(c)
                ],
            }
            for c in coverages
        ]

    # 2. Re-author jobs — existing pages out of sync with the code.
    reauthor_payload: list[dict[str, Any]] = []
    if include_reauthor and reauthor_jobs_max > 0:
        drifts = audit_wiki_drift(
            str(WIKI_ROOT),
            _project_source_root,
            limit=reauthor_jobs_max,
            domain_filter=domain,
        )
        reauthor_jobs = build_reauthor_jobs(
            drifts,
            wiki_page_port=wiki_page_port,
            source_root_resolver=_project_source_root,
            today=today,
        )
        reauthor_payload = [serialise_reauthor_job(j) for j in reauthor_jobs]

    # 3. Cluster jobs — bottom-up heat clusters.
    cluster_payload: list[dict[str, Any]] = []
    total_clusters_eligible = 0
    if memories:
        clusters = build_clusters(
            memories,
            domain=domain,
            min_memories=min_memories,
            min_avg_heat=min_avg_heat,
            wiki_page_port=wiki_page_port,
            skip_recently_authored=True,
        )
        total_clusters_eligible = len(clusters)
        cluster_jobs = build_jobs(clusters, existing_pages, today=today)
        # Reserve space for coverage + reauthor jobs in the user-specified limit.
        already_used = len(coverage_payload) + len(reauthor_payload)
        cluster_budget = max(0, limit - already_used)
        cluster_payload = [serialise_job(j) for j in cluster_jobs[:cluster_budget]]

    # Order: coverage → reauthor → cluster. Coverage anchors the
    # structural backbone, reauthor fixes existing pages, cluster fills
    # in new topical material.
    payload = coverage_payload + reauthor_payload + cluster_payload

    if not payload and not memories:
        return {
            "jobs": [],
            "total_clusters_eligible": 0,
            "instructions": (
                "No memories available and no coverage gaps found. Use "
                "`remember` to seed."
            ),
            "memory_pool_size": 0,
        }

    return {
        "jobs": payload,
        "coverage_jobs_returned": len(coverage_payload),
        "reauthor_jobs_returned": len(reauthor_payload),
        "cluster_jobs_returned": len(cluster_payload),
        "total_clusters_eligible": total_clusters_eligible,
        "returned": len(payload),
        "memory_pool_size": len(memories),
        "domain_filter": domain or "(all)",
        "domain_coverage_summary": domain_coverages_summary,
        "instructions": instructions_for_llm(
            len(payload),
            total_clusters_eligible,
            len(coverage_payload),
            len(reauthor_payload),
        ),
    }
