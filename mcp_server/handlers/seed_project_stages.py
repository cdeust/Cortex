"""Stage functions for seed_project -- discovery extraction from a codebase.

Each stage scans a specific aspect of the project directory and returns
a list of discovery dicts with title, content, and tags.

Constants live in seed_project_constants.py.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp_server.handlers.seed_project_constants import (
    CI_FILES,
    CONFIG_FILES,
    DOC_DIRS,
    DOC_GLOBS,
    ENTRY_POINT_NAMES,
    EXT_MAP,
    HEAT_BY_TYPE,
    IGNORE_DIRS,
)


def heat_for_tags(tags: list[str]) -> float:
    """Determine initial heat based on discovery type tags."""
    if "project-structure" in tags or "structural_summary" in tags:
        return HEAT_BY_TYPE["structural_summary"]
    if "documentation" in tags:
        return HEAT_BY_TYPE["documentation"]
    if "entry-point" in tags:
        return HEAT_BY_TYPE["entry_point"]
    if "config" in tags or "project-setup" in tags:
        return HEAT_BY_TYPE["config"]
    if "ci-cd" in tags or "devops" in tags:
        return HEAT_BY_TYPE["ci_cd"]
    return 0.7


def _safe_read(path: Path, max_bytes: int = 65536) -> str:
    """Read a file up to max_bytes. Returns empty string on error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except OSError:
        return ""


def _walk_pruned(root: Path):
    """Walk ``root`` skipping IGNORE_DIRS and not following symlinks/junctions.

    Uses ``os.walk(followlinks=False)`` with in-place pruning of ``dirnames``
    so that ignored directories (node_modules, .venv, __pycache__, etc.) are
    never descended into. This is the canonical cross-platform idiom and is
    required on Windows to avoid traversing NTFS junctions and reparse points.
    Yields ``Path`` objects for every file under the pruned tree.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        dp = Path(dirpath)
        for name in filenames:
            yield dp / name


def _detect_languages(root: Path) -> list[str]:
    """Detect primary programming languages from file extensions."""
    ext_counts: dict[str, int] = {}
    for p in _walk_pruned(root):
        lang = EXT_MAP.get(p.suffix.lower())
        if lang:
            ext_counts[lang] = ext_counts.get(lang, 0) + 1
    return sorted(ext_counts, key=lambda lang: ext_counts[lang], reverse=True)[:5]


def _top_level_layout(root: Path) -> list[str]:
    """Return top-level directories and key files."""
    items = []
    try:
        for entry in sorted(root.iterdir()):
            if entry.name.startswith(".") and entry.name not in {".github"}:
                continue
            if entry.name in IGNORE_DIRS:
                continue
            prefix = "\U0001f4c1 " if entry.is_dir() else "\U0001f4c4 "
            items.append(f"{prefix}{entry.name}")
    except PermissionError:
        pass
    return items[:30]


def stage_configs(root: Path, max_bytes: int) -> list[dict]:
    """Extract project config files."""
    discoveries = []
    for name in CONFIG_FILES:
        p = root / name
        if p.exists() and p.is_file():
            content = _safe_read(p, max_bytes)
            if content.strip():
                discoveries.append(
                    {
                        "title": f"Project config: {name}",
                        "content": f"# {name}\n\n{content}",
                        "tags": ["config", "project-setup", name.replace(".", "_")],
                    }
                )
    return discoveries


def _harvest_root_docs(root: Path, max_bytes: int) -> list[dict]:
    """Harvest documentation files from the project root."""
    discoveries = []
    seen: set[Path] = set()
    for pattern in DOC_GLOBS:
        for p in root.glob(pattern):
            if p.is_file() and p not in seen:
                seen.add(p)
                content = _safe_read(p, max_bytes)
                if content.strip():
                    discoveries.append(
                        {
                            "title": f"Documentation: {p.name}",
                            "content": f"# {p.name}\n\n{content}",
                            "tags": ["documentation", "project-context"],
                            "_path": p,
                        }
                    )
    return discoveries


def _harvest_doc_dirs(root: Path, max_bytes: int, seen: set[Path]) -> list[dict]:
    """Harvest documentation from docs directories."""
    discoveries = []
    for doc_dir in DOC_DIRS:
        d = root / doc_dir
        if not d.exists() or not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.suffix.lower() not in {
                ".md",
                ".rst",
                ".txt",
                ".adoc",
            }:
                continue
            if p in seen:
                continue
            seen.add(p)
            content = _safe_read(p, max_bytes)
            if content.strip():
                discoveries.append(
                    {
                        "title": f"Doc: {p.relative_to(root)}",
                        "content": f"# {p.name}\n\n{content}",
                        "tags": [
                            "documentation",
                            "adr" if "adr" in doc_dir else "docs",
                        ],
                    }
                )
    return discoveries


def stage_docs(root: Path, max_bytes: int) -> list[dict]:
    """Harvest documentation files."""
    root_docs = _harvest_root_docs(root, max_bytes)
    seen = {d.get("_path") for d in root_docs if "_path" in d}
    for d in root_docs:
        d.pop("_path", None)
    dir_docs = _harvest_doc_dirs(root, max_bytes, seen)
    return (root_docs + dir_docs)[:20]


def stage_entry_points(root: Path, max_bytes: int) -> list[dict]:
    """Find and read entry point files."""
    discoveries = []
    for p in _walk_pruned(root):
        # Skip anything inside dist-info/egg-info build metadata
        if any(part.endswith((".dist-info", ".egg-info")) for part in p.parts):
            continue
        if p.name in ENTRY_POINT_NAMES and p.is_file():
            content = _safe_read(p, max_bytes)
            if content.strip():
                rel = p.relative_to(root)
                discoveries.append(
                    {
                        "title": f"Entry point: {rel}",
                        "content": f"# Entry point: {rel}\n\n```\n{content}\n```",
                        "tags": ["entry-point", "architecture"],
                    }
                )
    return discoveries[:5]


def _scan_cicd_dir(root: Path, directory: Path) -> list[dict]:
    """Scan a CI/CD directory for YAML workflow files."""
    found = []
    files = list(directory.glob("**/*.yml")) + list(directory.glob("**/*.yaml"))
    for f in files[:3]:
        content = _safe_read(f, 32768)
        if content.strip():
            found.append(
                {
                    "title": f"CI/CD: {f.relative_to(root)}",
                    "content": f"# CI/CD: {f.relative_to(root)}\n\n```yaml\n{content}\n```",
                    "tags": ["ci-cd", "devops"],
                }
            )
    return found


def stage_cicd(root: Path) -> list[dict]:
    """Detect CI/CD configuration."""
    found = []
    for path_str in CI_FILES:
        p = root / path_str
        if not p.exists():
            continue
        if p.is_dir():
            found.extend(_scan_cicd_dir(root, p))
        else:
            content = _safe_read(p, 32768)
            if content.strip():
                found.append(
                    {
                        "title": f"CI/CD: {p.name}",
                        "content": f"# {p.name}\n\n```\n{content}\n```",
                        "tags": ["ci-cd", "devops"],
                    }
                )
    return found[:5]


def stage_structural_summary(root: Path) -> dict:
    """Build a structural summary memory."""
    layout = _top_level_layout(root)
    languages = _detect_languages(root)

    content_lines = [
        f"# Project structure: {root.name}",
        f"\n**Root:** `{root}`",
        f"\n**Primary languages:** {', '.join(languages) or 'unknown'}",
        "\n## Top-level layout",
    ] + [f"- {item}" for item in layout]

    return {
        "title": f"Project structure: {root.name}",
        "content": "\n".join(content_lines),
        "tags": ["project-structure", "architecture", "seeded"],
    }


def collect_all_discoveries(root: Path, max_bytes: int) -> list[dict]:
    """Run all stages and return combined discovery list."""
    discoveries: list[dict] = []
    discoveries.append(stage_structural_summary(root))
    discoveries.extend(stage_configs(root, max_bytes))
    discoveries.extend(stage_docs(root, max_bytes))
    discoveries.extend(stage_entry_points(root, max_bytes))
    discoveries.extend(stage_cicd(root))
    return discoveries
