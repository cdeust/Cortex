"""Stage 4: PRD Generation — produce specification sections and file manifest."""

from __future__ import annotations

import re

from mcp_server.errors import AnalysisError
from mcp_server.handlers.pipeline.helpers import (
    extract_text,
    finding_to_prd_type,
    get_cognitive_context,
    log,
    trunc,
    try_parse_json,
)


PRD_SECTION_DEFS = [
    (
        "overview",
        "Generate the PRD Overview section: problem statement, goals, scope, stakeholders, success metrics.",
    ),
    (
        "requirements",
        "Generate Functional Requirements (FR table) and Non-Functional Requirements (NFR table).",
    ),
    (
        "user-stories",
        "Generate User Stories in standard format with acceptance criteria.",
    ),
    (
        "technical",
        "Generate Technical Specification: file change manifest, API design, data models, architecture decisions.",
    ),
    ("acceptance", "Generate Acceptance Criteria with KPI tables."),
    (
        "roadmap",
        "Generate Implementation Roadmap: phased delivery plan, milestones, dependencies, risk mitigation.",
    ),
    ("tests", "Generate Test Plan: unit, integration, E2E, performance tests."),
    ("jira", "Generate JIRA ticket breakdown: Epic with child stories."),
    (
        "verification",
        "Generate Verification Checklist: traceability matrix, review checklist.",
    ),
]


def _build_prd_sections(prd_name: str) -> list[dict]:
    """Build section metadata list with filenames."""
    return [
        {"key": key, "file": f"PRD-{prd_name}-{key}.md", "prompt": prompt}
        for key, prompt in PRD_SECTION_DEFS
    ]


def _build_codebase_context_str(ctx: dict, cognitive_ctx: str) -> str:
    """Assemble the full codebase context string for PRD prompts."""
    return "\n".join(
        [
            "=== CODEBASE ARCHITECTURE ===",
            trunc(ctx["codebaseCtx"]["architecture"], 2000),
            "",
            "=== KEY TYPES & PROTOCOLS ===",
            ", ".join(ctx["codebaseCtx"]["patterns"][:30]),
            "",
            "=== IMPORTS & DEPENDENCIES ===",
            "\n".join(ctx["codebaseCtx"]["dependencies"][:30]),
            "",
            "=== SOURCE STRUCTURE ===",
            "\n".join(
                f"{d['dir']}/ ({d['count']} files)" for d in ctx["sourceDirs"][:10]
            ),
            "",
            "=== IMPACT ANALYSIS ===",
            trunc(ctx.get("impactText", ""), 1000),
            "",
            "=== STRATEGY ===",
            ctx.get("stratName", ""),
            (f"\n=== COGNITIVE PROFILE ===\n{cognitive_ctx}" if cognitive_ctx else ""),
        ]
    )


async def _generate_sections(
    client,
    prd_sections: list[dict],
    top_finding: dict,
    prd_type: str,
    codebase_context_str: str,
) -> dict[str, dict]:
    """Generate each PRD section via the enhance_prompt tool."""
    prd_files: dict[str, dict] = {}
    for section in prd_sections:
        log(f"  generating {section['key']}...")
        result = await client.call(
            "ai_architect_enhance_prompt",
            {
                "prompt": (
                    f"{section['prompt']}\n\n"
                    f"Finding: {top_finding.get('title')}\n"
                    f"{trunc(top_finding.get('description'), 800)}\n\n"
                    f"This is a {prd_type} PRD. Reference actual files, types, "
                    f"and modules from the target codebase."
                ),
                "context": codebase_context_str,
                "max_iterations": 5,
            },
        )
        content = extract_text(result)
        if len(content) < 100:
            raise AnalysisError(
                f'PRD section "{section["key"]}" generation failed '
                f"-- returned {len(content)} chars (minimum 100)",
                {"stage": 4, "section": section["key"], "length": len(content)},
            )
        prd_files[section["key"]] = {"filename": section["file"], "content": content}
    return prd_files


def _validate_sections(
    prd_sections: list[dict],
    prd_files: dict[str, dict],
) -> None:
    """Raise AnalysisError if any section is missing or too short."""
    missing = [
        s
        for s in prd_sections
        if not prd_files.get(s["key"], {}).get("content")
        or len(prd_files[s["key"]]["content"]) < 100
    ]
    if missing:
        raise AnalysisError(
            f"PRD incomplete: {len(missing)} of {len(prd_sections)} sections failed "
            f"-- {', '.join(s['key'] for s in missing)}",
            {"stage": 4, "missing": [s["key"] for s in missing]},
        )


def _parse_manifest_json(manifest_text: str) -> list:
    """Parse file manifest JSON, trying bracket extraction as fallback."""
    file_manifest = try_parse_json(manifest_text)
    if isinstance(file_manifest, list):
        return file_manifest

    if isinstance(manifest_text, str):
        bracket_match = re.search(r"\[[\s\S]*\]", manifest_text)
        if bracket_match:
            parsed = try_parse_json(bracket_match.group())
            if isinstance(parsed, list):
                return parsed

    return []


async def _extract_file_manifest(client, ctx: dict, prd_files: dict) -> list:
    """Extract the file change manifest from the technical spec."""
    log("  extracting file manifest...")
    manifest_result = await client.call(
        "ai_architect_enhance_prompt",
        {
            "prompt": (
                "Extract the ordered file change manifest from this PRD technical spec.\n"
                "Return ONLY a valid JSON array. Each element:\n"
                '{"path": "relative/file/path", "changeType": "create|modify|delete", '
                '"description": "what to do", "acRefs": ["AC-1"]}\n\n'
                f"Technical spec:\n{trunc(prd_files.get('technical', {}).get('content', ''), 3000)}"
            ),
            "context": (
                f"Source dirs: {', '.join(d['dir'] for d in ctx['sourceDirs'][:10])}\n"
                f"Key types: {', '.join(ctx['codebaseCtx']['patterns'][:20])}"
            ),
            "max_iterations": 3,
        },
    )

    manifest_text = extract_text(manifest_result)
    file_manifest = _parse_manifest_json(manifest_text)

    if not file_manifest:
        log(f"  manifest extraction failed, raw response: {trunc(manifest_text, 500)}")
        raise AnalysisError(
            "PRD technical spec produced empty file manifest -- no implementation targets.",
            {
                "stage": 4,
                "prdType": ctx.get("prdType"),
                "finding": ctx["topFindings"][0].get("title"),
            },
        )
    return file_manifest


def _compute_prd_name(top_finding: dict) -> str:
    """Derive a sanitized PRD name from the finding title."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", (top_finding.get("title") or "untitled"))[
        :40
    ].lower()


async def stage_prd(client, ctx: dict) -> None:
    """Execute the full PRD generation stage."""
    log("Stage 4: PRD Generation")
    top_finding = ctx["topFindings"][0]
    prd_type = finding_to_prd_type(top_finding)
    prd_name = _compute_prd_name(top_finding)

    codebase_context_str = _build_codebase_context_str(
        ctx, get_cognitive_context(ctx["codebasePath"])
    )
    prd_sections = _build_prd_sections(prd_name)

    prd_files = await _generate_sections(
        client, prd_sections, top_finding, prd_type, codebase_context_str
    )
    _validate_sections(prd_sections, prd_files)
    log(f"  all {len(prd_sections)} PRD sections generated")

    file_manifest = await _extract_file_manifest(client, ctx, prd_files)

    ctx.update(
        {
            "prdType": prd_type,
            "prdName": prd_name,
            "prdSections": prd_sections,
            "prdFiles": prd_files,
            "fileManifest": file_manifest,
            "codebaseContextStr": codebase_context_str,
        }
    )
    ctx["stages"][4] = {
        "status": "ok",
        "sections": len(prd_sections),
        "manifest_files": len(file_manifest),
    }
    log(f"  {len(prd_sections)} sections, {len(file_manifest)} manifest files")
