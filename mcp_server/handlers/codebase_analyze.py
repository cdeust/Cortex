"""Handler: codebase_analyze — scan a project and store code structure as memories.

Walks a project directory, parses source files using tree-sitter AST
(with regex fallback), and stores one memory per file with symbols as
entities and imports as relationships. Then runs cross-file resolution,
call graph extraction, and community detection.

Incremental by default: only processes files whose content hash changed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from mcp_server.core.codebase_parser import (
    EXT_TO_LANG,
    build_memory_content,
    parse_file,
)
from mcp_server.handlers.codebase_analyze_helpers import (
    CODEBASE_AGENT_CONTEXT,
    FILE_TAG_PREFIX,
    HASH_TAG_PREFIX,
    collect_source_files,
    load_existing_hashes,
    mark_stale,
    persist_entities,
)
from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": (
        "Walk a codebase and store its structure as memories using tree-"
        "sitter AST parsing (with regex fallback for unsupported "
        "languages). One memory per file, with symbols as entities and "
        "imports as relationships; then cross-file symbol resolution, "
        "call-graph extraction, and community detection over the call "
        "graph. Incremental — only re-processes files whose content hash "
        "changed since last run (tracked via HASH_TAG_PREFIX tags). Use "
        "this on first onboarding to a serious codebase, or after a major "
        "refactor that invalidates symbol assumptions. Distinct from "
        "`seed_project` (5-stage shallow structural sweep, no AST), "
        "`backfill_memories` (Claude Code conversations, not source "
        "files), `wiki_seed_codebase` (seeds wiki pages from .md docs), "
        "and `ingest_codebase` (downstream PRD-generator consumer). "
        "Mutates memories + entities + relationships tables. Latency "
        "varies (~10s-10min depending on tree size). Returns "
        "{files_analyzed, files_skipped, memories_written, entities_"
        "created, relationships_created}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "directory": {
                "type": "string",
                "description": "Root directory of the codebase to analyze. Defaults to the current working directory.",
                "examples": ["/Users/alice/code/cortex"],
            },
            "languages": {
                "type": "array",
                "description": (
                    "Restrict analysis to specific languages by tree-sitter "
                    "grammar name. Omit to auto-detect from file extensions."
                ),
                "items": {
                    "type": "string",
                    "enum": [
                        "python",
                        "javascript",
                        "typescript",
                        "rust",
                        "go",
                        "java",
                        "swift",
                        "c",
                        "cpp",
                        "ruby",
                    ],
                },
                "default": [],
                "examples": [["python"], ["typescript", "javascript"]],
            },
            "max_files": {
                "type": "integer",
                "description": "Maximum number of files to process per call. Cap to avoid runaway analysis on monorepos.",
                "default": 500,
                "minimum": 1,
                "maximum": 50000,
                "examples": [100, 500, 5000],
            },
            "max_file_size_kb": {
                "type": "integer",
                "description": "Skip files larger than this many kilobytes (typically generated files or binary blobs).",
                "default": 100,
                "minimum": 1,
                "maximum": 4096,
                "examples": [100, 256],
            },
            "incremental": {
                "type": "boolean",
                "description": "Only re-process files whose content hash changed since the last analysis. Disable for a clean rescan.",
                "default": True,
            },
            "dry_run": {
                "type": "boolean",
                "description": "Report what would be analyzed and stored without writing any memories.",
                "default": False,
            },
            "domain": {
                "type": "string",
                "description": "Cognitive domain to tag analysis memories with. Auto-detected from directory if omitted.",
                "examples": ["cortex", "auth-service"],
            },
        },
    },
}

CODEBASE_SOURCE = "codebase_analyze"
CODEBASE_TAG = "codebase"
LANG_TAG_PREFIX = "lang:"
DEFAULT_MAX_FILES = 500
DEFAULT_MAX_FILE_SIZE_KB = 100

_store: MemoryStore | None = None


def _log(msg: str) -> None:
    print(f"[codebase-analyze] {msg}", file=sys.stderr)


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


def _parse_args(args: dict[str, Any] | None) -> tuple:
    """Extract and default handler arguments."""
    args = args or {}
    directory = Path(args.get("directory", "") or os.getcwd()).expanduser().resolve()
    languages = args.get("languages")
    max_files = int(args.get("max_files", DEFAULT_MAX_FILES))
    max_kb = int(args.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB))
    incremental = args.get("incremental", True)
    dry_run = args.get("dry_run", False)
    domain = args.get("domain", "")
    return directory, languages, max_files, max_kb * 1024, incremental, dry_run, domain


def _build_tags(rel_path: str, analysis: Any) -> list[str]:
    """Build memory tags for a file analysis."""
    tags = [
        CODEBASE_TAG,
        f"{FILE_TAG_PREFIX}{rel_path}",
        f"{HASH_TAG_PREFIX}{analysis.content_hash}",
        f"{LANG_TAG_PREFIX}{analysis.language}",
    ]
    for sym in analysis.definitions[:10]:
        tags.append(f"symbol:{sym.name}")
    return tags


def _set_memory_metadata(store: MemoryStore, memory_id: int) -> None:
    """Mark memory as semantic with boosted heat and importance."""
    try:
        store._conn.execute(
            "UPDATE memories SET store_type = 'semantic', "
            "heat = 0.7, importance = 0.5 WHERE id = %s",
            (memory_id,),
        )
        store._conn.commit()
    except Exception:
        pass


async def _store_file(
    root: Path,
    rel_path: str,
    analysis: Any,
    domain: str,
    store: MemoryStore,
) -> tuple[int | None, int, int]:
    """Store a single file as a memory with entities.

    Returns:
        Tuple of (memory_id, entities, relationships).
    """
    result = await remember_handler(
        {
            "content": build_memory_content(analysis),
            "tags": _build_tags(rel_path, analysis),
            "directory": str(root),
            "domain": domain,
            "source": CODEBASE_SOURCE,
            "force": True,
            "agent_topic": CODEBASE_AGENT_CONTEXT,
        }
    )
    memory_id = result.get("memory_id")
    if not result.get("stored") or not memory_id:
        return None, 0, 0

    _set_memory_metadata(store, memory_id)
    ents, rels = persist_entities(store, analysis, memory_id, domain or "code")
    return memory_id, ents, rels


def _parse_one_file(path: str, content: str) -> Any:
    """Parse a file with tree-sitter AST or regex fallback."""
    from mcp_server.core.ast_parser import is_available, parse_file_ast

    if is_available():
        return parse_file_ast(path, content.encode(errors="replace"))
    return parse_file(path, content)


async def _process_files(
    source_files: list[Path],
    root: Path,
    existing: dict[str, tuple[int, str]],
    incremental: bool,
    domain: str,
    store: MemoryStore,
) -> tuple[int, int, int, int, int, set[str], list[Any], dict[str, str]]:
    """Process source files: parse, diff, store.

    Returns counters, seen paths, analyses, and file contents map.
    """
    new_count, updated_count, unchanged_count = 0, 0, 0
    total_entities, total_relationships = 0, 0
    seen_paths: set[str] = set()
    all_analyses: list[Any] = []
    file_contents: dict[str, str] = {}

    for source_path in source_files:
        rel_path = _resolve_relative(source_path, root)
        seen_paths.add(rel_path)
        content = _safe_read(source_path)
        if content is None:
            continue
        file_contents[rel_path] = content
        analysis = _parse_one_file(rel_path, content)
        all_analyses.append(analysis)
        if incremental and rel_path in existing:
            if existing[rel_path][1] == analysis.content_hash:
                unchanged_count += 1
                continue
        _, ents, rels = await _store_file(root, rel_path, analysis, domain, store)
        total_entities += ents
        total_relationships += rels
        updated_count += 1 if rel_path in existing else 0
        new_count += 0 if rel_path in existing else 1

    return (
        new_count,
        updated_count,
        unchanged_count,
        total_entities,
        total_relationships,
        seen_paths,
        all_analyses,
        file_contents,
    )


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Analyze a codebase and store its structure as Cortex memories."""
    root, languages, max_files, max_bytes, incremental, dry_run, domain = _parse_args(
        args
    )

    if not root.exists() or not root.is_dir():
        return {"analyzed": False, "reason": f"directory not found: {root}"}

    _log(f"scanning {root} (max_files={max_files}, incremental={incremental})")
    source_files = collect_source_files(root, languages, max_files, max_bytes)
    _log(f"found {len(source_files)} source files")

    if dry_run:
        langs = list({EXT_TO_LANG.get(f.suffix.lower(), "?") for f in source_files})
        return {
            "analyzed": False,
            "dry_run": True,
            "directory": str(root),
            "source_files": len(source_files),
            "languages": langs,
        }

    store = _get_store()
    existing = load_existing_hashes(store) if incremental else {}
    if incremental:
        _log(f"loaded {len(existing)} existing file hashes")

    new_c, upd_c, unch_c, ents, rels, seen, analyses, contents = await _process_files(
        source_files,
        root,
        existing,
        incremental,
        domain,
        store,
    )
    stale = _mark_deleted(existing, seen, store, incremental)

    # Phase 2: cross-file resolution, type references, communities
    graph_stats = _run_graph_analysis(analyses, contents, store, domain or "code")

    _log(f"done: {new_c} new, {upd_c} updated, {unch_c} unchanged, {stale} stale")
    _log(f"graph: {graph_stats}")
    return {
        "analyzed": True,
        "directory": str(root),
        "source_files": len(source_files),
        "new": new_c,
        "updated": upd_c,
        "unchanged": unch_c,
        "stale_marked": stale,
        "entities": ents,
        "relationships": rels,
        "graph": graph_stats,
        "languages": list(
            {EXT_TO_LANG.get(f.suffix.lower(), "?") for f in source_files}
        ),
    }


def _run_graph_analysis(
    analyses: list[Any],
    file_contents: dict[str, str],
    store: MemoryStore,
    domain: str,
) -> dict[str, int]:
    """Run cross-file resolution, type references, and communities."""
    from mcp_server.core.codebase_graph import (
        detect_communities,
        extract_inheritance,
        resolve_all_imports,
    )
    from mcp_server.core.codebase_type_resolver import resolve_type_references
    from mcp_server.handlers.codebase_analyze_helpers import (
        persist_community_tags,
        persist_file_edge,
        persist_inheritance_edge,
    )

    import_edges = resolve_all_imports(analyses)
    type_ref_edges = resolve_type_references(analyses, file_contents)
    all_file_edges = list(set(import_edges + type_ref_edges))
    inherit_edges = extract_inheritance(analyses)
    communities = detect_communities(all_file_edges, [])

    file_rels = persist_file_edge(store, all_file_edges, domain)
    inherit_rels = persist_inheritance_edge(store, inherit_edges, domain)
    persist_community_tags(store, communities)

    return {
        "import_edges": len(import_edges),
        "type_ref_edges": len(type_ref_edges),
        "total_file_edges": len(all_file_edges),
        "inheritance_edges": len(inherit_edges),
        "communities": len(set(communities.values())) if communities else 0,
        "file_edges_stored": file_rels,
        "inherit_edges_stored": inherit_rels,
    }


def _resolve_relative(source_path: Path, root: Path) -> str:
    """Resolve a source path to a root-relative string."""
    try:
        return str(source_path.relative_to(root))
    except ValueError:
        return str(source_path)


def _safe_read(source_path: Path) -> str | None:
    """Read a file, returning None on failure."""
    try:
        return source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _mark_deleted(
    existing: dict[str, tuple[int, str]],
    seen_paths: set[str],
    store: MemoryStore,
    incremental: bool,
) -> int:
    """Mark memories for files no longer on disk as stale."""
    if not incremental:
        return 0
    deleted_ids = [mid for path, (mid, _) in existing.items() if path not in seen_paths]
    return mark_stale(store, deleted_ids)
