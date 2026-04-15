"""Seed the wiki from a project's existing markdown docs (Phase 7.3).

Purpose: first-run users get concrete pages in their wiki within
minutes of install, without waiting for session-derived memories to
accumulate.

Scanned by default:
  README.md, CHANGELOG.md, CONTRIBUTING.md, ARCHITECTURE.md,
  HISTORY.md, SECURITY.md, docs/**/*.md, ADR-*.md, adr/*.md

Each file becomes ONE memory (via remember), tagged `seed:codebase`
and the detected kind. The wiki pipeline is run afterward so the
imports produce claim events → concepts → drafts → pages in one call.

Per-file size capped at 8 kB (head-only — prevents a 50-page README
from flooding the extractor). Binary and huge files skipped.

Never raises per-file; collects errors in the summary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


schema = {
    "description": (
        "Bootstrap the wiki from markdown documents already in the repo "
        "(README, CHANGELOG, CONTRIBUTING, ARCHITECTURE, docs/**/*.md, "
        "adr/**/*.md, ADR-*.md, AGENTS.md, CLAUDE.md). Each file becomes "
        "one memory tagged `seed:codebase` plus an inferred kind tag, then "
        "(unless skipped) the full `wiki_pipeline` runs to convert those "
        "memories into claim_events → concepts → drafts → published pages. "
        "Use this on first install so the wiki is non-empty within minutes "
        "instead of waiting for session memories to accumulate. Distinct "
        "from `seed_project` (analyzes the codebase structure to seed "
        "memories, not docs), `codebase_analyze` (tree-sitter AST "
        "structural memories), and `backfill_memories` (Claude Code "
        "conversation history). Per-file size capped (8 kB head); binaries "
        "and node_modules-style paths skipped. Latency varies (~30s-3min "
        "depending on doc count). Returns {files_found, imported, errors, "
        "pipeline?: per-stage counts}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "repo_root": {
                "type": "string",
                "description": (
                    "Absolute path to the repository to scan for seed-eligible "
                    "markdown. Defaults to the current working directory."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
            "max_files": {
                "type": "integer",
                "description": (
                    "Hard cap on the number of files imported in one call. "
                    "Files past this cap are silently dropped (priority order: "
                    "README, CHANGELOG, ARCHITECTURE, docs/, ADRs, …)."
                ),
                "default": 50,
                "minimum": 1,
                "maximum": 1000,
                "examples": [25, 50, 200],
            },
            "max_bytes_per_file": {
                "type": "integer",
                "description": (
                    "Per-file content size cap (head-only, prevents a giant "
                    "README from flooding the extractor). Truncated content "
                    "gets a `[...truncated]` marker."
                ),
                "default": 8192,
                "minimum": 256,
                "maximum": 1048576,
                "examples": [4096, 8192, 32768],
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "List the files that WOULD be imported (with inferred "
                    "kind and size) without writing any memories or running "
                    "the pipeline."
                ),
                "default": False,
                "examples": [False, True],
            },
            "run_pipeline": {
                "type": "boolean",
                "description": (
                    "After importing the docs, immediately invoke "
                    "`wiki_pipeline` to convert them into published pages. "
                    "Set false to import-only and run the pipeline yourself "
                    "later."
                ),
                "default": True,
                "examples": [True, False],
            },
        },
    },
}


# Priority-ordered; scanner walks the repo once and keeps files whose
# relative path matches any of these patterns.
_SEED_PATTERNS: list[str] = [
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "ARCHITECTURE.md",
    "HISTORY.md",
    "SECURITY.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/**/*.md",
    "adr/**/*.md",
    "ADR-*.md",
    ".claude/**/*.md",
]

# Skip these paths even if they match a pattern (vendored / generated).
_SKIP_PATH_FRAGMENTS = (
    "/node_modules/",
    "/.venv/",
    "/.build/",
    "/.git/",
    "/dist/",
    "/build/",
    "/__pycache__/",
    "/.cache/",
    "/.generated/",
)


def _kind_for(rel_path: str) -> str:
    low = rel_path.lower()
    if "adr" in low or "decision" in low:
        return "adr"
    if "architecture" in low:
        return "spec"
    if "convention" in low or "style" in low:
        return "convention"
    if "lesson" in low or "postmortem" in low:
        return "lesson"
    if low.startswith("readme") or low.endswith("/readme.md"):
        return "note"
    return "note"


def _collect_files(
    root: Path, max_files: int, max_bytes: int
) -> list[tuple[Path, str]]:
    """Return [(abs_path, rel_path)] for seed-worthy markdown."""
    root = root.resolve()
    seen: set[Path] = set()
    results: list[tuple[Path, str]] = []
    for pattern in _SEED_PATTERNS:
        for p in sorted(root.glob(pattern)):
            try:
                pr = p.resolve()
            except OSError:
                continue
            if pr in seen:
                continue
            seen.add(pr)
            rel = str(pr.relative_to(root)).replace("\\", "/")
            if any(frag in f"/{rel}" for frag in _SKIP_PATH_FRAGMENTS):
                continue
            if not pr.is_file():
                continue
            try:
                size = pr.stat().st_size
            except OSError:
                continue
            if size == 0 or size > 2_000_000:
                continue
            _ = max_bytes  # capped at read time, not filter time
            results.append((pr, rel))
            if len(results) >= max_files:
                return results
    return results


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    repo_root = Path(args.get("repo_root") or Path.cwd()).resolve()
    max_files = int(args.get("max_files", 50))
    max_bytes = int(args.get("max_bytes_per_file", 8192))
    dry_run = bool(args.get("dry_run", False))
    run_pipeline = bool(args.get("run_pipeline", True))

    from mcp_server.handlers.remember import handler as h_remember

    files = _collect_files(repo_root, max_files, max_bytes)
    if not files:
        return {
            "files_found": 0,
            "imported": 0,
            "note": "no seed-eligible markdown found in this repo",
            "dry_run": dry_run,
        }

    if dry_run:
        return {
            "files_found": len(files),
            "preview": [
                {"path": rel, "kind": _kind_for(rel), "size": p.stat().st_size}
                for p, rel in files
            ],
            "dry_run": True,
        }

    imported = 0
    errors: list[str] = []
    for p, rel in files:
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            if len(content) > max_bytes:
                content = content[:max_bytes] + "\n\n[...truncated]"
            domain = repo_root.name or "seed"
            kind = _kind_for(rel)
            result = await h_remember(
                {
                    "content": content,
                    "tags": ["seed:codebase", f"kind:{kind}", f"file:{rel}"],
                    "domain": domain,
                    "source": f"seed:{rel}",
                    "force": True,
                }
            )
            if result.get("stored") or result.get("memory_id"):
                imported += 1
        except Exception as e:
            errors.append(f"{rel}: {e}")

    summary: dict[str, Any] = {
        "files_found": len(files),
        "imported": imported,
        "errors": errors[:10],
        "error_count": len(errors),
        "dry_run": False,
    }

    if run_pipeline and imported > 0:
        try:
            from mcp_server.handlers.wiki_pipeline import handler as h_pipeline

            pipe = await h_pipeline({"limit_per_stage": 1000})
            summary["pipeline"] = {
                "claims_inserted": pipe.get("claims_inserted", 0),
                "concepts_inserted": pipe.get("concepts_inserted", 0),
                "drafts_approved": pipe.get("drafts_approved", 0),
                "pages_published": pipe.get("pages_published", 0),
            }
        except Exception as e:
            summary["pipeline"] = {"error": str(e)}

    return summary
