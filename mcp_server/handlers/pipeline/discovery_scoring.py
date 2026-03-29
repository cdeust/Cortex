"""Scoring and validation helpers for the discovery stage."""

from __future__ import annotations

import os
from typing import Any

from mcp_server.errors import AnalysisError
from mcp_server.handlers.pipeline.helpers import trunc
from mcp_server.shared.similarity import jaccard_similarity
from mcp_server.shared.text import extract_keywords


async def score_findings(
    client,
    findings: list[dict],
    codebase_kw: set,
    max_findings: int,
) -> tuple[list[dict], list[dict]]:
    """Score findings against codebase keywords. Returns (scored, top)."""
    scored: list[dict] = []
    jaccard_min = float(os.environ.get("PIPELINE_JACCARD_MIN", "0.02"))

    for f in findings[:50]:
        finding_kw = extract_keywords(
            (f.get("title") or "") + " " + (f.get("description") or "")
        )
        similarity = jaccard_similarity(codebase_kw, finding_kw)
        if similarity < jaccard_min:
            continue
        score = await client.call(
            "ai_architect_compound_score",
            {
                "relevance": min(
                    1.0, similarity * 2 + (f.get("relevance_score") or 0.3) * 0.3
                ),
                "uniqueness": 0.6,
                "impact": (f.get("importance") or 5) / 10,
                "confidence": min(1.0, similarity + (f.get("relevance_score") or 0.3)),
            },
        )
        compound = _extract_compound(score)
        scored.append({**f, "compound": compound, "similarity": similarity})

    scored.sort(key=lambda x: x["compound"], reverse=True)
    return scored, scored[:max_findings]


def _extract_compound(score: Any) -> float:
    """Extract compound score from a score response."""
    if isinstance(score, dict):
        return score.get("compound_score") or score.get("weighted_total") or 0.5
    return 0.5


def validate_top_findings(
    top_findings: list[dict],
    codebase_kw_count: int,
) -> None:
    """Raise AnalysisError if findings fail quality checks."""
    if not top_findings:
        raise AnalysisError(
            "No findings with meaningful codebase relevance (all Jaccard < 0.02)",
            {"stage": 1, "codebaseKeywords": codebase_kw_count},
        )
    top_compound = top_findings[0]["compound"]
    threshold = float(os.environ.get("PIPELINE_COMPOUND_THRESHOLD", "0.4"))
    if top_compound < threshold:
        raise AnalysisError(
            f"Top finding compound score {top_compound:.3f} is below threshold ({threshold})",
            {
                "stage": 1,
                "top": {
                    "id": top_findings[0].get("id"),
                    "title": top_findings[0].get("title"),
                    "compound": top_compound,
                    "similarity": top_findings[0]["similarity"],
                },
            },
        )


def build_codebase_ctx(
    file_entries: list[dict],
    project_doc: str,
) -> dict[str, Any]:
    """Assemble codebase context from scanned files."""
    all_types = [
        s["text"] for f in file_entries for s in f["symbols"] if s["type"] == "type"
    ]
    all_imports = [
        s["text"] for f in file_entries for s in f["symbols"] if s["type"] == "import"
    ]
    return {
        "files": file_entries,
        "architecture": trunc(project_doc, 5000),
        "patterns": list(dict.fromkeys(all_types))[:50],
        "dependencies": list(dict.fromkeys(all_imports))[:50],
    }


async def save_discovery_artifact(
    client,
    finding_id: str,
    root_files: list[str],
    source_dirs: list[dict],
    source_files_read: int,
    codebase_ctx: dict,
    findings: list[dict],
    scored: list[dict],
    top_findings: list[dict],
) -> None:
    """Persist the discovery stage artifact."""
    await client.call(
        "ai_architect_save_context",
        {
            "stage_id": 1,
            "finding_id": finding_id,
            "artifact": {
                "codebase": {
                    "root_entries": len(root_files),
                    "source_dirs": [d for d in source_dirs[:10]],
                    "source_files_read": source_files_read,
                    "types": len(codebase_ctx["patterns"]),
                    "imports": len(codebase_ctx["dependencies"]),
                },
                "task": {
                    "total": len(findings),
                    "scored": len(scored),
                    "top": [
                        {
                            "id": f.get("id"),
                            "title": f.get("title"),
                            "compound": f["compound"],
                        }
                        for f in top_findings
                    ],
                },
            },
        },
    )
