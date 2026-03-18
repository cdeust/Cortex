"""Artifact builders for the implementation stage.

Generates finding reports, digest JSON, writes PRD files,
and commits pipeline artifacts.
"""

from __future__ import annotations

import json

from mcp_server.handlers.pipeline.helpers import log, trunc


async def write_prd_files(client, ctx: dict, wt_args: dict) -> list[str]:
    """Write PRD section files and commit them."""
    log("  writing PRD files...")
    prd_paths: list[str] = []
    for section in ctx["prdSections"]:
        prd_file = ctx["prdFiles"].get(section["key"])
        if not prd_file or not prd_file.get("content"):
            continue
        prd_path = f".pipeline/prd/{prd_file['filename']}"
        await client.call(
            "ai_architect_fs_write",
            {
                "path": prd_path,
                "content": prd_file["content"],
                **wt_args,
            },
        )
        prd_paths.append(prd_path)

    if prd_paths:
        await client.call(
            "ai_architect_git_commit",
            {
                "message": f"[{ctx['findingId']}] stage-6: PRD -- {len(prd_paths)} specification files",
                "files": prd_paths,
                **wt_args,
            },
        )
    return prd_paths


def _build_report_header(ctx: dict, top_finding: dict) -> list[str]:
    """Build the metadata header lines for a finding report."""
    verify = ctx.get("verify", {})
    verdict = verify.get("verdict") if isinstance(verify, dict) else ""
    score = verify.get("score") if isinstance(verify, dict) else ""
    return [
        f"# {top_finding.get('title')}",
        "",
        f"**ID:** {ctx['findingId']}",
        f"**Actor:** {top_finding.get('actor')}",
        f"**Category:** {top_finding.get('relevance_category_label') or top_finding.get('domain')}",
        f"**Compound:** {top_finding['compound']:.3f}",
        f"**Verification:** {verdict} ({score})",
        f"**Strategy:** {ctx.get('stratName', '')}",
    ]


def _build_finding_report(
    ctx: dict,
    implemented_files: list[dict],
    tool_calls: int,
) -> str:
    """Build the markdown finding report content."""
    top_finding = ctx["topFindings"][0]
    lines = _build_report_header(ctx, top_finding)
    lines.extend(
        [
            "",
            "## Description",
            "",
            trunc(top_finding.get("description"), 1500),
            "",
            "## Impact",
            "",
            trunc(ctx.get("impactText", ""), 1500),
            "",
            "## Implementation",
            "",
            f"{len(implemented_files)} source files generated:",
            *[
                f"- `{f['path']}` [{f.get('changeType')}] ({f['size']} chars)"
                for f in implemented_files
            ],
            "",
            "---",
            f"*JARVIS pipeline * {tool_calls} tool calls*",
        ]
    )
    return "\n".join(lines)


def _build_digest_json(ctx: dict, implemented_files: list[dict]) -> str:
    """Build the JSON digest string."""
    return json.dumps(
        {
            "finding_id": ctx["findingId"],
            "task_source": ctx["taskPath"],
            "codebase": {
                "path": ctx["codebasePath"],
                "root_entries": len(ctx["rootFiles"]),
                "types": len(ctx["codebaseCtx"]["patterns"]),
            },
            "findings": {
                "total": len(ctx["findings"]),
                "scored": len(ctx["scored"]),
                "top": [
                    {
                        "id": f.get("id"),
                        "title": f.get("title"),
                        "compound": f["compound"],
                    }
                    for f in ctx["topFindings"]
                ],
            },
            "prd": {
                "type": ctx["prdType"],
                "files": [s["file"] for s in ctx["prdSections"]],
                "manifest_files": len(ctx["fileManifest"]),
            },
            "implementation": {
                "files": implemented_files,
                "total": len(implemented_files),
            },
        },
        indent=2,
    )


async def write_pipeline_artifacts(
    client,
    ctx: dict,
    implemented_files: list[dict],
    wt_args: dict,
) -> None:
    """Write the finding report and digest JSON, then commit."""
    report_path = f".pipeline/findings/{ctx['findingId']}.md"
    report_content = _build_finding_report(ctx, implemented_files, client.tool_calls)
    await client.call(
        "ai_architect_fs_write",
        {"path": report_path, "content": report_content, **wt_args},
    )

    digest_path = f".pipeline/digests/{ctx['findingId']}.json"
    digest_content = _build_digest_json(ctx, implemented_files)
    await client.call(
        "ai_architect_fs_write",
        {"path": digest_path, "content": digest_content, **wt_args},
    )

    await client.call(
        "ai_architect_git_commit",
        {
            "message": f"[{ctx['findingId']}] stage-6: pipeline artifacts -- report + digest",
            "files": [report_path, digest_path],
            **wt_args,
        },
    )
