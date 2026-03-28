"""Pipeline → Cortex memory bridge.

Every significant pipeline event is stored in Cortex memory so the
cognitive profile evolves with each pipeline run. Events include:
discovery findings, impact scores, strategy selections, PRD generation
outcomes, verification verdicts, implementation files, and HOR results.

Call ``trace(ctx, event, content, tags)`` from any stage to persist
a pipeline observation to Cortex. The function is fire-and-forget —
failures are logged but never block the pipeline.
"""

from __future__ import annotations

import sys
from typing import Any


def _log(msg: str) -> None:
    print(f"[pipeline-trace] {msg}", file=sys.stderr)


async def trace(
    ctx: dict[str, Any],
    event: str,
    content: str,
    tags: list[str] | None = None,
) -> None:
    """Store a pipeline event in Cortex memory.

    Args:
        ctx: Pipeline context (must contain codebasePath).
        event: Short event label (e.g. "discovery", "impact", "prd").
        content: The memory content to store.
        tags: Additional tags (auto-merged with pipeline tags).
    """
    try:
        from mcp_server.handlers.remember import handler as remember_handler

        base_tags = ["pipeline", f"stage:{event}"]
        finding_id = ctx.get("findingId", "")
        if finding_id:
            base_tags.append(f"finding:{finding_id}")
        if tags:
            base_tags.extend(tags)

        await remember_handler(
            {
                "content": content,
                "tags": base_tags,
                "directory": ctx.get("codebasePath", ""),
                "source": "tool",
                "agent_topic": "pipeline",
            }
        )
    except Exception as exc:
        _log(f"memory trace failed ({event}): {exc}")


async def trace_discovery(ctx: dict[str, Any], scored: list[dict]) -> None:
    """Trace discovery results: top findings with compound scores."""
    top = scored[:3]
    lines = [f"Pipeline discovery scored {len(scored)} findings:"]
    for f in top:
        title = f.get("title", "untitled")
        compound = f.get("compound", 0)
        lines.append(f"  - {title} (compound={compound:.3f})")
    await trace(ctx, "discovery", "\n".join(lines), ["discovery", "findings"])


async def trace_impact(ctx: dict[str, Any], impact_text: str) -> None:
    """Trace impact analysis result."""
    await trace(
        ctx,
        "impact",
        f"Impact analysis for {ctx.get('findingId', '?')}: {impact_text[:500]}",
        ["impact", "analysis"],
    )


async def trace_strategy(ctx: dict[str, Any], strategy_name: str) -> None:
    """Trace strategy selection."""
    await trace(
        ctx,
        "strategy",
        f"Selected strategy '{strategy_name}' for finding {ctx.get('findingId', '?')}",
        ["strategy", "decision"],
    )


async def trace_prd(
    ctx: dict[str, Any], section_count: int, manifest_count: int
) -> None:
    """Trace PRD generation result."""
    await trace(
        ctx,
        "prd",
        f"Generated PRD with {section_count} sections and {manifest_count} manifest files "
        f"for finding {ctx.get('findingId', '?')}",
        ["prd", "generation"],
    )


async def trace_verification(
    ctx: dict[str, Any],
    verdict: str,
    score: float,
    claim_count: int,
) -> None:
    """Trace verification verdict."""
    await trace(
        ctx,
        "verification",
        f"Verification verdict={verdict} score={score:.3f} claims={claim_count} "
        f"for finding {ctx.get('findingId', '?')}",
        ["verification", "verdict"],
    )


async def trace_implementation(
    ctx: dict[str, Any],
    file_count: int,
    files: list[dict],
) -> None:
    """Trace implementation results."""
    file_list = ", ".join(f.get("path", "?") for f in files[:5])
    await trace(
        ctx,
        "implementation",
        f"Implemented {file_count} files for {ctx.get('findingId', '?')}: {file_list}",
        ["implementation", "code"],
    )


async def trace_hor(ctx: dict[str, Any], passed: int, total: int) -> None:
    """Trace HOR rules result."""
    await trace(
        ctx,
        "hor",
        f"HOR rules: {passed}/{total} passed for finding {ctx.get('findingId', '?')}",
        ["hor", "rules", "quality"],
    )


async def trace_pipeline_complete(ctx: dict[str, Any], result: dict) -> None:
    """Trace full pipeline completion."""
    status = result.get("status", "unknown")
    pr_url = result.get("pr", "")
    tool_calls = result.get("tool_calls", 0)
    await trace(
        ctx,
        "complete",
        f"Pipeline {status} for {ctx.get('findingId', '?')}: "
        f"{tool_calls} tool calls, PR={pr_url or 'none'}",
        ["pipeline", "complete", status],
    )
