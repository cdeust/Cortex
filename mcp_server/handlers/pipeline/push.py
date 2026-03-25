"""Stages 9-10: Push branch and create pull request."""

from __future__ import annotations


from mcp_server.handlers.pipeline.helpers import log, trunc


def _build_metrics_table(ctx: dict, verify: dict, tool_calls: int) -> list[str]:
    """Build the metrics markdown table rows."""
    top_finding = ctx["topFindings"][0]
    return [
        "### Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Compound | {top_finding['compound']:.3f} |",
        f"| Verify | {verify.get('verdict') if isinstance(verify, dict) else ''} "
        f"({verify.get('score') if isinstance(verify, dict) else ''}) |",
        f"| HOR | {ctx.get('horPassed', 0)}/{ctx.get('horTotal', 0)} |",
        f"| Strategy | {ctx.get('stratName', '')} |",
        f"| Tools | {tool_calls} |",
        f"| YAML Audit | {ctx.get('totalRulesChecked', 0)} rules / "
        f"{ctx.get('totalFlagsRaised', 0)} flags |",
    ]


def _build_file_lists(ctx: dict) -> tuple[str, str]:
    """Build implementation and PRD file list strings."""
    impl_list = (
        "\n".join(
            f"- `{f['path']}` [{f.get('changeType')}]"
            for f in ctx.get("implementedFiles", [])
        )
        or "No source files generated"
    )
    prd_list = "\n".join(f"- `{s['file']}`" for s in ctx["prdSections"])
    return impl_list, prd_list


def _build_pr_body(client, ctx: dict) -> str:
    """Assemble the PR description markdown."""
    top_finding = ctx["topFindings"][0]
    verify = ctx.get("verify", {})
    impl_list, prd_list = _build_file_lists(ctx)

    sections = [
        f"## {top_finding.get('title')}",
        "",
        f"**{ctx['findingId']}** | {top_finding.get('actor')} | "
        f"{top_finding.get('relevance_category_label') or top_finding.get('domain')}",
        "",
        trunc(top_finding.get("description"), 600),
        "",
        *_build_metrics_table(ctx, verify, client.tool_calls),
        "",
        "### PRD Files",
        "",
        prd_list,
        "",
        "### Implementation Files",
        "",
        impl_list,
    ]

    if ctx.get("auditResults"):
        audit_summary = "\n".join(
            f"| {a['family']} | {a['rulesChecked']} | {a['flagsRaised']} |"
            for a in ctx["auditResults"]
        )
        sections.extend(
            [
                "",
                f"### YAML Audit Results\n\n| Family | Rules | Flags |\n|---|---|---|\n{audit_summary}",
            ]
        )

    sections.extend(["", "---", f"*Cortex pipeline * {client.tool_calls} tool calls*"])
    return "\n".join(sections)


async def _cleanup_worktree(client, ctx: dict) -> None:
    """Remove the git worktree if one was created."""
    if not ctx.get("worktreePath"):
        return
    try:
        await client.call(
            "ai_architect_git_worktree_remove",
            {"worktree_path": ctx["worktreePath"]},
        )
        log("  worktree removed")
    except Exception as e:
        log(f"  worktree cleanup: {e}")


async def _save_pr_artifact(client, ctx: dict, pr_url: str) -> None:
    """Persist the PR creation artifact."""
    await client.call(
        "ai_architect_save_context",
        {
            "stage_id": 10,
            "finding_id": ctx["findingId"],
            "artifact": {
                "status": "delivered",
                "branch": ctx["branchName"],
                "pr": pr_url,
                "tools": client.tool_calls,
                "prd_files": len(ctx["prdSections"]),
                "implemented_files": len(ctx.get("implementedFiles", [])),
                "audit": {
                    "rules_checked": ctx.get("totalRulesChecked", 0),
                    "flags_raised": ctx.get("totalFlagsRaised", 0),
                },
            },
        },
    )


async def stage_push_and_pr(client, ctx: dict) -> None:
    """Execute push and PR creation stages."""
    log("Stage 9: Push")
    await client.call(
        "ai_architect_git_push",
        {
            "branch": ctx["branchName"],
            "force": False,
            **ctx.get("wtArgs", {}),
        },
    )

    log("Stage 10: PR")
    top_finding = ctx["topFindings"][0]
    body = _build_pr_body(client, ctx)

    pr = await client.call(
        "ai_architect_github_create_pr",
        {
            "title": f"[pipeline] {trunc(top_finding.get('title'), 60)}",
            "body": body,
            "head": ctx["branchName"],
            "base": "main",
        },
    )
    pr_url = (
        (pr.get("url") or pr.get("html_url") or pr.get("number"))
        if isinstance(pr, dict)
        else pr
    )

    await _save_pr_artifact(client, ctx, pr_url)
    await _cleanup_worktree(client, ctx)

    ctx["prUrl"] = pr_url
    ctx["stages"][9] = {"status": "ok"}
    ctx["stages"][10] = {"status": "ok", "pr": pr_url}
    log(f"  PR: {pr_url}")
