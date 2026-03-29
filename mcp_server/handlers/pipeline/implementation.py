"""Stage 6: Implementation -- generate code, write PRD files, commit artifacts."""

from __future__ import annotations

import os

from mcp_server.errors import AnalysisError
from mcp_server.handlers.pipeline.helpers import extract_text, log, trunc
from mcp_server.handlers.pipeline.implementation_artifacts import (
    write_pipeline_artifacts,
    write_prd_files,
)
from mcp_server.handlers.pipeline.memory_trace import trace_implementation


async def _setup_branch(client, ctx: dict) -> tuple[str, str | None, dict]:
    """Create worktree or branch. Returns (branch_name, worktree_path, wt_args)."""
    branch_name = f"pipeline/{ctx['findingId']}"
    worktree_path = None
    try:
        wt = await client.call(
            "ai_architect_git_worktree_add",
            {"branch_name": branch_name, "base": "main"},
        )
        worktree_path = (
            (wt.get("worktree_path") or wt.get("path"))
            if isinstance(wt, dict)
            else None
        )
        log(f"  worktree: {worktree_path or 'created'}")
    except Exception as e:
        log(f"  worktree failed ({e}), falling back to branch")
        await client.call(
            "ai_architect_git_branch",
            {"branch_name": branch_name, "base": "main"},
        )
    wt_args = {"worktree_path": worktree_path} if worktree_path else {}
    return branch_name, worktree_path, wt_args


def _normalize_manifest_entry(file: dict | str) -> dict | None:
    """Normalize a manifest entry to a dict, or None if invalid."""
    if isinstance(file, str):
        return {"path": file, "changeType": "create", "description": file, "acRefs": []}
    if not isinstance(file, dict) or not file.get("path"):
        log(f"  skip: invalid manifest entry: {trunc(str(file), 100)}")
        return None
    return file


async def _read_existing_content(client, file_path: str, wt_args: dict) -> str:
    """Read existing file content for modify operations."""
    try:
        existing = await client.call(
            "ai_architect_fs_read",
            {"path": file_path, **wt_args},
        )
        return (
            existing
            if isinstance(existing, str)
            else (existing.get("content", "") if isinstance(existing, dict) else "")
        )
    except Exception:
        return ""


def _build_implementation_context(existing_content: str, ctx: dict) -> str:
    """Build the context string for code generation."""
    return "\n\n".join(
        filter(
            None,
            [
                f"=== EXISTING FILE ===\n{trunc(existing_content, 2000)}"
                if existing_content
                else "",
                f"=== PRD TECHNICAL SPEC ===\n{trunc(ctx['prdFiles'].get('technical', {}).get('content', ''), 1500)}",
                f"=== CODEBASE CONTEXT ===\n{trunc(ctx.get('codebaseContextStr', ''), 1500)}",
            ],
        )
    )


async def _generate_and_write(client, file: dict, ctx: dict, wt_args: dict) -> str:
    """Generate code via enhance_prompt and write to filesystem. Returns code."""
    code_result = await client.call(
        "ai_architect_enhance_prompt",
        {
            "prompt": (
                f"Implement {file['path']}: {file.get('description', '')}.\n"
                f"Acceptance criteria: {', '.join(file.get('acRefs', []))}.\n"
                f"Change type: {file.get('changeType', 'create')}.\n"
                f"Return ONLY the complete file content -- no markdown fences, no explanation."
            ),
            "context": _build_implementation_context(
                await _read_existing_content(client, file["path"], wt_args)
                if file.get("changeType") == "modify"
                else "",
                ctx,
            ),
            "max_iterations": 5,
        },
    )
    generated_code = extract_text(code_result)
    if len(generated_code) >= 10:
        await client.call(
            "ai_architect_fs_write",
            {"path": file["path"], "content": generated_code, **wt_args},
        )
    return generated_code


async def _implement_single_file(
    client,
    file: dict,
    ctx: dict,
    wt_args: dict,
) -> dict | None:
    """Generate and commit code for a single manifest file."""
    log(f"  implementing: {file['path']} [{file.get('changeType')}]")

    generated_code = await _generate_and_write(client, file, ctx, wt_args)
    if len(generated_code) < 10:
        log(f"    skip: too short ({len(generated_code)} chars)")
        return None

    filename = os.path.basename(file["path"])
    await client.call(
        "ai_architect_git_commit",
        {
            "message": f"[{ctx['findingId']}] stage-6: {filename} -- {', '.join(file.get('acRefs', []))}",
            "files": [file["path"]],
            **wt_args,
        },
    )
    log(f"    done: {filename} ({len(generated_code)} chars)")
    return {
        "path": file["path"],
        "changeType": file.get("changeType"),
        "size": len(generated_code),
    }


async def _implement_manifest(client, ctx: dict, wt_args: dict) -> list[dict]:
    """Implement all manifest files, returning the list of implemented file records."""
    implemented: list[dict] = []
    for file in ctx["fileManifest"]:
        entry = _normalize_manifest_entry(file)
        if entry is None:
            continue
        result = await _implement_single_file(client, entry, ctx, wt_args)
        if result:
            implemented.append(result)
    return implemented


async def stage_implementation(client, ctx: dict) -> None:
    """Execute the full implementation stage."""
    log("Stage 6: Implementation")

    branch_name, worktree_path, wt_args = await _setup_branch(client, ctx)
    implemented_files = await _implement_manifest(client, ctx, wt_args)

    prd_paths = await write_prd_files(client, ctx, wt_args)
    await write_pipeline_artifacts(client, ctx, implemented_files, wt_args)

    if not implemented_files:
        raise AnalysisError(
            "Implementation stage produced 0 source files",
            {
                "stage": 6,
                "manifest_count": len(ctx["fileManifest"]),
                "prd_files": len(prd_paths),
            },
        )

    ctx.update(
        {
            "branchName": branch_name,
            "worktreePath": worktree_path,
            "wtArgs": wt_args,
            "implementedFiles": implemented_files,
        }
    )
    await trace_implementation(ctx, len(implemented_files), implemented_files)
    ctx["stages"][6] = {
        "status": "ok",
        "files": len(implemented_files),
        "prd_files": len(prd_paths),
    }
    log(f"  {len(implemented_files)} files implemented, {len(prd_paths)} PRD files")
