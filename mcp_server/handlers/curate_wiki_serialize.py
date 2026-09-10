"""curate_wiki's wire-transport serializers and LLM-facing instructions.

source: ADR-0385"""

from __future__ import annotations

from typing import Any


def serialise_job(job: Any) -> dict[str, Any]:
    """Flatten a cluster-driven CurationJob for MCP wire transport."""
    c = job.cluster
    return {
        "job_type": "cluster",
        "suggested_path": c.suggested_path,
        "suggested_kind": c.suggested_kind,
        "topic": c.topic,
        "domain": c.domain,
        "memory_count": len(c.memory_ids),
        "memory_ids": c.memory_ids,
        "top_entities": c.entities[:8],
        "avg_heat": round(c.avg_heat, 3),
        "earliest_memory_at": c.earliest_at,
        "latest_memory_at": c.latest_at,
        "related_pages": job.related_pages,
        "prompt": job.prompt,
    }


def serialise_reauthor_job(job: Any) -> dict[str, Any]:
    """Flatten a ReauthorJob for MCP wire transport.

    source: ADR-0385"""
    return {
        "job_type": "reauthor",
        "suggested_path": job.wiki_path,  # rewrite in place
        "suggested_kind": job.kind or "explanation",
        "domain": job.domain,
        "reasons": job.reasons,
        "cited_source_files": job.cited_source_files[:20],
        "missing_source_files": job.missing_source_files[:10],
        "prompt": job.prompt,
    }


def serialise_coverage_job(job: Any) -> dict[str, Any]:
    """Flatten a CoverageJob for MCP wire transport.

    source: ADR-0385"""
    return {
        "job_type": "coverage",
        "suggested_path": job.suggested_path,
        "suggested_kind": job.suggested_kind,
        "scope_name": job.scope_name,
        "scope_title": job.scope_title,
        "domain": job.domain,
        "supporting_memory_ids": job.supporting_memory_ids,
        "related_pages": job.related_pages,
        "prompt": job.prompt,
    }


def instructions_for_llm(
    n_jobs: int,
    n_clusters_eligible: int,
    n_coverage: int,
    n_reauthor: int,
) -> str:
    """The recipe the conversational Opus 4.7 follows when consuming jobs."""
    if n_jobs == 0:
        return (
            f"No authoring jobs returned. {n_clusters_eligible} clusters "
            "were eligible. If you expected jobs, relax `min_memories` "
            "or `min_avg_heat`, pass `recent_only=false`, or check that "
            "domains have uncovered scopes (`include_coverage=true`)."
        )
    n_cluster = n_jobs - n_coverage - n_reauthor
    return (
        f"Auto-curator returned {n_jobs} job(s): {n_coverage} structural "
        f"(coverage) + {n_reauthor} re-author (existing pages out of sync) + "
        f"{n_cluster} topical (cluster), out of "
        f"{n_clusters_eligible} eligible clusters. Process them IN ORDER:\n\n"
        "  1. Coverage jobs first — anchor pages (architecture, services, "
        "api, data-flow) ground every subsequent topical page.\n"
        "  2. Re-author jobs next — existing pages drifted from the "
        "codebase. Each carries `reasons` and `missing_source_files`. "
        "Rewrite the page in place at `suggested_path` (same as the "
        "page's current path); preserve every accurate claim, fix the "
        "stale ones, fill template gaps. Don't delete the page even "
        "for a deprecated feature — prefix the title with '(deprecated)' "
        "and link to the replacement.\n"
        "  3. Cluster jobs last — new topical pages from memory heat.\n\n"
        "For each job:\n"
        "  * Read `prompt` — it carries everything you need.\n"
        "  * For coverage and re-author jobs, consult the actual source "
        "tree (open the project's directories) to verify against the "
        "current code.\n"
        "  * For `adr` kind (task-record), the body MUST carry: Status, "
        "Entry, Mandatory elements, How, Result, Serves, Alternatives, "
        "References — in that order.\n"
        "  * Write via `wiki_write(path=<job.suggested_path>, "
        "content=<your authored Markdown>, tags=['wiki', 'llm-authored', "
        "<topic-or-scope>, <domain>], memory_ids=<the subset of this "
        "job's memory_ids/supporting_memory_ids you actually drew on>)`. "
        "Pass memory_ids honestly — it's the durable record of which "
        "memories this page documents (wiki.citations), not a checklist "
        "to satisfy. For re-author jobs this overwrites the existing "
        "file.\n"
        "  * Call `curate_wiki` again when this batch is done.\n\n"
        "Do not skip structure. Do not dump raw memory content; "
        "synthesise. Each page should be 8-15 KB of substantive "
        "authored prose, not a template."
    )
