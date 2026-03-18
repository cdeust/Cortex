"""Composition root for the 11-stage ai-architect pipeline.

Each stage is a function receiving (client, ctx) where ctx accumulates
stage outputs. JARVIS injects cognitive context from its own profiles.

Stage implementations live in mcp_server.handlers.pipeline.* modules.
This file is the thin orchestrator: schema + handler + backward-compat aliases.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.mcp_client_pool import get_client
from mcp_server.handlers.pipeline.helpers import log as _log
from mcp_server.handlers.pipeline.audit import stage_audit
from mcp_server.handlers.pipeline.discovery import stage_discovery
from mcp_server.handlers.pipeline.implementation import stage_implementation
from mcp_server.handlers.pipeline.prd import stage_prd
from mcp_server.handlers.pipeline.push import stage_push_and_pr
from mcp_server.handlers.pipeline.stages import (
    stage_hor,
    stage_impact,
    stage_init,
    stage_interview,
    stage_strategy,
)
from mcp_server.handlers.pipeline.verification import stage_verification

# ── Schema ─────────────────────────────────────────────────────────────────

schema = {
    "description": "Drive the ai-architect pipeline end-to-end: discovery -> impact -> strategy -> PRD -> verification -> implementation -> PR. Connects to ai-architect MCP server over stdio.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "codebase_path": {
                "type": "string",
                "description": "Absolute path to the target repository",
            },
            "task_path": {
                "type": "string",
                "description": "Path to findings/task JSON file",
            },
            "context_path": {
                "type": "string",
                "description": "Path to supporting documentation (file or directory)",
            },
            "github_repo": {
                "type": "string",
                "description": "GitHub repo (owner/name) for PR creation",
            },
            "server": {
                "type": "string",
                "description": "MCP server name from mcp-connections.json (default: ai-architect)",
            },
            "max_findings": {
                "type": "number",
                "description": "Maximum findings to process (default: 5)",
            },
        },
        "required": ["codebase_path", "task_path"],
    },
}

# ── Stage Order ────────────────────────────────────────────────────────────

NON_FATAL_STAGES = {"7: HOR", "8: Audit"}

STAGE_SEQUENCE = [
    ("0: Init", "stage_init"),
    ("1: Discovery", "stage_discovery"),
    ("2: Impact", "stage_impact"),
    ("3: Strategy", "stage_strategy"),
    ("4: PRD", "stage_prd"),
    ("4.5: Interview", "stage_interview"),
    ("5: Verification", "stage_verification"),
    ("6: Implementation", "stage_implementation"),
    ("7: HOR", "stage_hor"),
    ("8: Audit", "stage_audit"),
    ("9-10: Push & PR", "stage_push_and_pr"),
]


# Map from name to function — resolved at import time, patchable by tests
_STAGE_FNS: dict[str, Any] = {
    "stage_init": stage_init,
    "stage_discovery": stage_discovery,
    "stage_impact": stage_impact,
    "stage_strategy": stage_strategy,
    "stage_prd": stage_prd,
    "stage_interview": stage_interview,
    "stage_verification": stage_verification,
    "stage_implementation": stage_implementation,
    "stage_hor": stage_hor,
    "stage_audit": stage_audit,
    "stage_push_and_pr": stage_push_and_pr,
}


# ── Main Handler ───────────────────────────────────────────────────────────


def _build_context(args: dict) -> dict[str, Any]:
    """Build the initial pipeline context from handler arguments."""
    return {
        "codebasePath": args["codebase_path"],
        "taskPath": args["task_path"],
        "contextPath": args.get("context_path"),
        "githubRepo": args.get("github_repo") or "",
        "maxFindings": args.get("max_findings") or 5,
        "stages": {},
    }


def _build_success_result(client, ctx: dict) -> dict:
    """Build the success response dict."""
    return {
        "status": "delivered",
        "finding_id": ctx.get("findingId"),
        "branch": ctx.get("branchName"),
        "pr": ctx.get("prUrl"),
        "tool_calls": client.tool_calls,
        "implemented_files": len(ctx.get("implementedFiles", [])),
        "prd_files": len(ctx.get("prdSections", [])),
        "hor": (
            f"{ctx.get('horPassed', 0)}/{ctx.get('horTotal', 0)}"
            if ctx.get("horPassed") is not None
            else None
        ),
        "audit": {
            "rules": ctx.get("totalRulesChecked", 0),
            "flags": ctx.get("totalFlagsRaised", 0),
        },
        "stages": ctx["stages"],
    }


async def handler(args: dict) -> dict:
    """Run all pipeline stages sequentially, accumulating context."""
    server_name = args.get("server") or "ai-architect"
    client = await get_client(server_name)
    ctx = _build_context(args)

    for label, fn_name in STAGE_SEQUENCE:
        stage_fn = _STAGE_FNS[fn_name]
        try:
            await stage_fn(client, ctx)
        except Exception as err:
            _log(f"STAGE FAILED [{label}]: {err}")
            ctx["stages"][label] = {"status": "error", "error": str(err)}

            if label in NON_FATAL_STAGES:
                _log("  (non-fatal, continuing)")
                continue

            return {
                "status": "error",
                "failed_stage": label,
                "error": str(err),
                "stages": ctx["stages"],
                "tool_calls": client.tool_calls,
            }

    return _build_success_result(client, ctx)
