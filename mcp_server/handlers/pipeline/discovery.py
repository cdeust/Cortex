"""Stage 1: Discovery -- codebase scanning, task loading, finding scoring."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from mcp_server.handlers.pipeline.discovery_scoring import (
    build_codebase_ctx,
    save_discovery_artifact,
    score_findings,
    validate_top_findings,
)
from mcp_server.handlers.pipeline.helpers import log, trunc
from mcp_server.handlers.pipeline.memory_trace import trace_discovery
from mcp_server.shared.text import extract_keywords

SOURCE_EXTS = re.compile(
    r"\.(swift|js|ts|py|go|rs|java|kt|rb|cs|c|cpp|h|m)$", re.IGNORECASE
)
MAX_SOURCE_FILES = 30


async def _read_project_docs(client, codebase_path: str) -> tuple[str, list[dict]]:
    """Read project documentation files. Returns (project_doc, file_entries)."""
    doc_files = [
        "CLAUDE.md",
        "README.md",
        "CONTRIBUTING.md",
        "docs/architecture.md",
        "Package.swift",
        "package.json",
    ]
    project_doc = ""
    file_entries: list[dict] = []

    for doc_file in doc_files:
        content = await client.call("ai_architect_fs_read", {"path": doc_file})
        text = (
            content
            if isinstance(content, str)
            else (content.get("content", "") if isinstance(content, dict) else "")
        )
        if len(text) > 50:
            project_doc += f"\n--- {doc_file} ---\n{trunc(text, 4000)}\n"
            file_entries.append(
                {"path": doc_file, "content": trunc(text, 4000), "symbols": []}
            )

    return project_doc, file_entries


async def _scan_source_dirs(client, root_files: list[str]) -> list[dict]:
    """Walk root entries and collect source directory metadata."""
    source_dirs: list[dict] = []
    for entry in root_files:
        if entry.startswith(".") or any(
            x in entry for x in ("node_modules", "__pycache__", ".build")
        ):
            continue
        sub = await client.call("ai_architect_fs_list", {"path": entry})
        sub_files = [
            os.path.basename(f)
            if isinstance(f, str)
            else os.path.basename(f.get("name", ""))
            for f in (sub.get("files", []) if isinstance(sub, dict) else [])
        ]
        if sub_files:
            source_dirs.append(
                {"dir": entry, "count": len(sub_files), "files": sub_files}
            )
    source_dirs.sort(key=lambda x: x["count"], reverse=True)
    return source_dirs


def _extract_symbols(text: str) -> list[dict]:
    """Extract import, type, and function symbols from source text."""
    symbols: list[dict] = []
    for m in re.finditer(
        r"^(?:import|require|from|use|using|#include)\s+.+$", text, re.MULTILINE
    ):
        symbols.append({"type": "import", "text": m.group().strip()})
    for m in re.finditer(
        r"^(?:(?:public|private|internal|open|final|abstract)\s+)*"
        r"(?:class|struct|protocol|interface|enum|trait)\s+(\w+)",
        text,
        re.MULTILINE,
    ):
        symbols.append({"type": "type", "text": m.group(1)})
    for m in re.finditer(
        r"^(?:(?:public|private|internal|open|static|async)\s+)*"
        r"(?:func|function|def|fn)\s+(\w+)",
        text,
        re.MULTILINE,
    ):
        symbols.append({"type": "func", "text": m.group(1)})
    return symbols


async def _read_source_files(
    client,
    source_dirs: list[dict],
    file_entries: list[dict],
) -> int:
    """Read key source files and append to file_entries. Returns count read."""
    source_files_read = 0
    for d in source_dirs[:8]:
        if source_files_read >= MAX_SOURCE_FILES:
            break
        for file_path in (d.get("files") or [])[:10]:
            if source_files_read >= MAX_SOURCE_FILES:
                break
            rel = file_path if isinstance(file_path, str) else file_path.get("name", "")
            if not SOURCE_EXTS.search(rel):
                continue
            content = await client.call(
                "ai_architect_fs_read", {"path": f"{d['dir']}/{rel}"}
            )
            text = (
                content
                if isinstance(content, str)
                else (content.get("content", "") if isinstance(content, dict) else "")
            )
            if len(text) > 20:
                symbols = _extract_symbols(text)
                file_entries.append(
                    {
                        "path": f"{d['dir']}/{rel}",
                        "content": trunc(text, 3000),
                        "symbols": symbols,
                    }
                )
                source_files_read += 1
    return source_files_read


def _load_context_docs(context_path: str | None) -> str:
    """Load supplementary context documents from path."""
    if not context_path:
        return ""
    cp = Path(context_path)
    if not cp.exists():
        return ""
    if cp.is_dir():
        parts: list[str] = []
        for cf in sorted(cp.iterdir())[:5]:
            if cf.suffix in (".md", ".json"):
                parts.append(
                    f"\n--- {cf.name} ---\n{trunc(cf.read_text(encoding='utf-8'), 2000)}\n"
                )
        return "".join(parts)
    return trunc(cp.read_text(encoding="utf-8"), 5000)


def _load_task(task_path: str) -> list[dict]:
    """Load and normalize findings from the task file."""
    raw_task = json.loads(Path(task_path).read_text(encoding="utf-8"))
    findings = (
        raw_task.get("findings") or raw_task
        if isinstance(raw_task, list)
        else raw_task.get("findings", [raw_task])
    )
    return findings


async def _scan_codebase(
    client,
    codebase_path: str,
) -> tuple[list[str], str, list[dict], dict[str, Any], int]:
    """Scan the codebase: root listing, docs, source dirs, context."""
    root_listing = await client.call("ai_architect_fs_list", {"path": "."})
    root_files = [
        f.replace(codebase_path + "/", "")
        for f in (
            root_listing.get("files", []) if isinstance(root_listing, dict) else []
        )
    ]
    log(f"  root: {len(root_files)} entries")

    project_doc, file_entries = await _read_project_docs(client, codebase_path)
    source_dirs = await _scan_source_dirs(client, root_files)
    source_files_read = await _read_source_files(client, source_dirs, file_entries)
    codebase_ctx = build_codebase_ctx(file_entries, project_doc)

    return root_files, project_doc, source_dirs, codebase_ctx, source_files_read


def _update_discovery_ctx(
    ctx: dict,
    root_files: list[str],
    source_dirs: list[dict],
    codebase_ctx: dict[str, Any],
    project_doc: str,
    context_doc: str,
    findings: list[dict],
    scored: list[dict],
    top_findings: list[dict],
    finding_id: str,
) -> None:
    """Update pipeline context with discovery results."""
    ctx.update(
        {
            "rootFiles": root_files,
            "sourceDirs": source_dirs,
            "codebaseCtx": codebase_ctx,
            "projectDoc": project_doc,
            "contextDoc": context_doc,
            "findings": findings,
            "scored": scored,
            "topFindings": top_findings,
            "findingId": finding_id,
        }
    )
    ctx["stages"][1] = {
        "status": "ok",
        "findings": len(findings),
        "top": len(top_findings),
    }


async def stage_discovery(client, ctx: dict) -> None:
    """Execute the full discovery stage."""
    log("Stage 1: Discovery")

    root_files, project_doc, source_dirs, codebase_ctx, _ = await _scan_codebase(
        client, ctx["codebasePath"]
    )

    findings = _load_task(ctx["taskPath"])
    log(f"  task: {len(findings)} findings")

    context_doc = _load_context_docs(ctx.get("contextPath"))
    codebase_kw = extract_keywords(
        project_doc
        + " "
        + " ".join(codebase_ctx["patterns"])
        + " "
        + " ".join(codebase_ctx["dependencies"])
    )
    log(f"  codebase keywords: {len(codebase_kw)}")

    scored, top_findings = await score_findings(
        client,
        findings,
        codebase_kw,
        ctx.get("maxFindings", 5),
    )
    validate_top_findings(top_findings, len(codebase_kw))

    finding_id = "TV-" + Path(ctx["taskPath"]).parent.name
    await save_discovery_artifact(
        client,
        finding_id,
        root_files,
        source_dirs,
        0,
        codebase_ctx,
        findings,
        scored,
        top_findings,
    )

    _update_discovery_ctx(
        ctx,
        root_files,
        source_dirs,
        codebase_ctx,
        project_doc,
        context_doc,
        findings,
        scored,
        top_findings,
        finding_id,
    )
    await trace_discovery(ctx, scored)
    log(f"  scored {len(scored)} findings, top {len(top_findings)}")
