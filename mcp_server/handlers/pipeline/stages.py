"""Lightweight pipeline stages: init, impact, strategy, interview, HOR."""

from __future__ import annotations

import json

from mcp_server.errors import AnalysisError
from mcp_server.handlers.pipeline.helpers import (
    extract_text,
    get_cognitive_context,
    log,
    trunc,
)
from mcp_server.handlers.pipeline.memory_trace import (
    trace_hor,
    trace_impact,
    trace_strategy,
)


async def stage_init(client, ctx: dict) -> None:
    """Stage 0: Initialize the pipeline on the target repo."""
    log("Stage 0: Init")
    init = await client.call(
        "ai_architect_init_pipeline",
        {
            "target_repo_path": ctx["codebasePath"],
            "data_dir": ".pipeline",
            "github_repo": ctx.get("githubRepo") or "",
        },
    )
    if isinstance(init, dict) and init.get("status") == "error":
        raise AnalysisError(
            f"Pipeline init blocked: {init.get('message')}",
            {"stage": 0},
        )
    ctx["stages"][0] = {
        "status": "ok",
        "target": init.get("target_repo") if isinstance(init, dict) else None,
    }
    log(f"  target: {init.get('target_repo') if isinstance(init, dict) else init}")


def _build_impact_prompt(ctx: dict, top_finding: dict) -> str:
    """Build the impact analysis prompt."""
    return (
        f"Analyze impact of this finding on the target codebase:\n\n"
        f"Finding: {top_finding.get('title')}\n"
        f"{trunc(top_finding.get('description'), 600)}\n\n"
        f"Codebase summary:\n{trunc(ctx['projectDoc'], 1000)}\n\n"
        f"Key types: {', '.join(ctx['codebaseCtx']['patterns'][:20])}\n"
        f"Source dirs: {', '.join(d['dir'] for d in ctx['sourceDirs'][:5])}"
    )


def _build_impact_context(ctx: dict, cognitive_ctx: str) -> str:
    """Build the context string for impact analysis."""
    base = (
        f"{trunc(ctx.get('contextDoc'), 1000)}\n\n"
        f"Codebase files analyzed: {len(ctx['codebaseCtx']['files'])}"
    )
    if cognitive_ctx:
        base += f"\n\n=== COGNITIVE PROFILE ===\n{cognitive_ctx}"
    return base


async def _trace_propagation(client, ctx: dict) -> dict:
    """Trace dependency propagation for the top source directory."""
    dep_graph = {d["dir"]: [] for d in ctx["sourceDirs"][:10]}
    source_module = ctx["sourceDirs"][0]["dir"] if ctx["sourceDirs"] else "src"
    return await client.call(
        "ai_architect_trace_propagation",
        {"source_module": source_module, "dependency_graph": dep_graph, "max_depth": 3},
    )


async def _save_impact_artifact(
    client,
    ctx: dict,
    top_finding: dict,
    impact_text: str,
    propagation: dict,
) -> None:
    """Save impact analysis artifact."""
    await client.call(
        "ai_architect_save_context",
        {
            "stage_id": 2,
            "finding_id": ctx["findingId"],
            "artifact": {
                "finding": {
                    "id": top_finding.get("id"),
                    "title": top_finding.get("title"),
                    "compound": top_finding["compound"],
                },
                "impact": impact_text,
                "propagation": propagation,
            },
        },
    )


async def stage_impact(client, ctx: dict) -> None:
    """Stage 2: Analyze impact of the top finding on the codebase."""
    log("Stage 2: Impact")
    top_finding = ctx["topFindings"][0]
    cognitive_ctx = get_cognitive_context(ctx["codebasePath"])

    impact = await client.call(
        "ai_architect_enhance_prompt",
        {
            "prompt": _build_impact_prompt(ctx, top_finding),
            "context": _build_impact_context(ctx, cognitive_ctx),
            "max_iterations": 3,
        },
    )

    propagation = await _trace_propagation(client, ctx)
    impact_text = extract_text(impact)
    await _save_impact_artifact(client, ctx, top_finding, impact_text, propagation)

    ctx["impactText"] = impact_text
    await trace_impact(ctx, impact_text)
    if len(impact_text) < 50:
        raise AnalysisError(
            "Impact analysis returned empty or trivial result",
            {"stage": 2, "length": len(impact_text)},
        )
    ctx["stages"][2] = {"status": "ok", "impact": trunc(impact_text, 200)}
    log(f"  impact: {trunc(impact_text, 120)}")


async def stage_strategy(client, ctx: dict) -> None:
    """Stage 3: Select implementation strategy."""
    log("Stage 3: Strategy")
    strategy = await client.call(
        "ai_architect_select_strategy",
        {
            "project_type": "software_pipeline",
            "complexity": "high",
            "characteristics": [
                "multi-module",
                "pipeline",
                "verification",
                "prompting",
            ],
        },
    )
    ctx["stratName"] = (
        strategy.get("selected", {}).get("name", "")
        if isinstance(strategy, dict)
        else ""
    )
    if not ctx["stratName"]:
        raise AnalysisError(
            "Strategy selection returned no strategy",
            {"stage": 3, "raw": strategy},
        )
    await trace_strategy(ctx, ctx["stratName"])
    ctx["stages"][3] = {"status": "ok", "strategy": ctx["stratName"]}
    log(f"  strategy: {ctx['stratName']}")


async def stage_interview(client, ctx: dict) -> None:
    """Stage 4.5: Interview gate — quality check before verification."""
    log("Stage 4.5: Interview Gate")
    overview = ctx["prdFiles"].get("overview", {}).get("content", "")
    requirements = ctx["prdFiles"].get("requirements", {}).get("content", "")

    interview = await client.call(
        "ai_architect_run_interview_gate",
        {
            "artifact": {
                "overview": trunc(overview, 2000),
                "requirements": trunc(requirements, 2000),
                "finding_id": ctx["findingId"],
                "manifest_files": len(ctx["fileManifest"]),
            },
            "finding_id": ctx["findingId"],
        },
    )

    if isinstance(interview, dict) and (
        interview.get("gate") == "reject" or interview.get("status") == "rejected"
    ):
        raise AnalysisError(
            f"Interview gate rejected: {interview.get('reason', 'quality check failed')}",
            {"stage": "4.5", "interview": interview},
        )

    ctx["stages"]["4.5"] = {"status": "ok", "gate": interview}
    interview_str = (
        json.dumps(interview) if isinstance(interview, dict) else str(interview)
    )
    log(f"  gate: {trunc(interview_str, 150)}")


async def stage_hor(client, ctx: dict) -> None:
    """Stage 7: HOR rules check."""
    log("Stage 7: HOR")
    top_finding = ctx["topFindings"][0]

    hor = await client.call(
        "ai_architect_run_hor_rules",
        {
            "artifact": {
                "title": top_finding.get("title"),
                "description": trunc(top_finding.get("description"), 500),
                "requirements": [
                    {
                        "id": f.get("id"),
                        "text": f.get("title"),
                        "acceptance_criteria": [
                            f"Compound score: {f['compound']:.3f}",
                            f"Source: {f.get('source_url', 'TechnicalVeil')}",
                        ],
                    }
                    for f in ctx["topFindings"][:3]
                ],
            },
            "base_score": 1.0,
        },
    )

    results = hor.get("results", []) if isinstance(hor, dict) else []
    passed = len([r for r in results if r.get("passed")])
    total = len(hor.get("results", [])) if isinstance(hor, dict) else 64

    ctx.update({"horPassed": passed, "horTotal": total})
    await trace_hor(ctx, passed, total)
    ctx["stages"][7] = {"status": "ok", "passed": passed, "total": total}
    log(f"  HOR: {passed}/{total} passed")
