"""Handler: wiki_purge — remove wiki pages that fail the current classifier.

Re-evaluates every authored wiki page against the current classifier rules
and deletes the ones that would no longer be admitted. Memories in the
PostgreSQL/SQLite store are left untouched — only the markdown files in
~/.claude/methodology/wiki/ are removed.

Use this after tightening classifier rules, after a backfill that
polluted the wiki, or whenever the wiki has drifted away from curated
knowledge toward session audit artefacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.core.wiki_classifier import classify_memory
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.shared.yaml_parser import parse_yaml_frontmatter

# ── Schema ─────────────────────────────────────────────────────────────

schema = {
    "description": (
        "Re-evaluate every authored wiki page against the current classifier "
        "rules and delete the ones that no longer pass the admission gate. "
        "Memories remain in the store (still available via recall); only the "
        "wiki markdown files are removed. Use this after a backfill that "
        "polluted the wiki with session artefacts (file access, URL access, "
        "stage reports, code reviews), or after tightening classifier rules. "
        "Returns keep/purge counts plus the list of purged relative paths. "
        "Always runs a dry-run by default — pass apply=true to actually delete."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "apply": {
                "type": "boolean",
                "description": (
                    "If true, actually delete the files. If false (default), "
                    "only report what would be purged."
                ),
                "default": False,
            },
            "kind": {
                "type": "string",
                "description": (
                    "Restrict the purge to a single page-kind directory. "
                    "Omit to scan all page kinds."
                ),
                "enum": [
                    "adr",
                    "conventions",
                    "guides",
                    "journal",
                    "lessons",
                    "notes",
                    "reference",
                    "specs",
                ],
                "examples": ["notes", "lessons"],
            },
        },
    },
}

# Directories that hold authored page-kind content. Anything else under the
# wiki root (_kinds, _rules, _views, _bibliography, _triggers, .generated)
# is deliberately left alone.
_PAGE_DIRS: frozenset[str] = frozenset(
    {
        "adr",
        "conventions",
        "guides",
        "journal",
        "lessons",
        "notes",
        "reference",
        "specs",
    }
)


def _parse_tags(raw: Any) -> list[str]:
    """Extract a list of tag strings from frontmatter value (list or CSV)."""
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if not isinstance(raw, str):
        return []
    stripped = raw.strip().strip("[]")
    return [t.strip().strip("'\"") for t in stripped.split(",") if t.strip()]


def _evaluate_page(md_path: Path) -> tuple[str | None, list[str]]:
    """Classify a single page. Returns (kind_or_None, tags)."""
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    r = parse_yaml_frontmatter(text)
    tags = _parse_tags(r.meta.get("tags"))
    body = r.body or ""
    lines = body.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    content = "\n".join(lines).strip() or str(r.meta.get("title", ""))
    return classify_memory(content, tags), tags


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Purge wiki pages that no longer pass the classifier."""
    args = args or {}
    apply = bool(args.get("apply", False))
    kind_filter = args.get("kind")

    root = Path(WIKI_ROOT).expanduser()
    if not root.exists():
        return {"error": f"wiki root does not exist: {root}"}

    target_dirs = {kind_filter} if kind_filter else _PAGE_DIRS
    kept: list[str] = []
    purged: list[str] = []
    errors: list[str] = []

    for md in root.rglob("*.md"):
        rel = md.relative_to(root)
        if rel.parts[0] not in target_dirs:
            continue
        try:
            decision, _tags = _evaluate_page(md)
            if decision is None:
                purged.append(str(rel))
                if apply:
                    md.unlink()
            else:
                kept.append(str(rel))
        except (OSError, ValueError) as exc:
            errors.append(f"{rel}: {exc}")

    # Clean up empty directories after an apply so the tree stays tidy.
    if apply and purged:
        for dir_path in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
            if (
                dir_path.is_dir()
                and not any(dir_path.iterdir())
                and not dir_path.name.startswith("_")
                and dir_path != root
            ):
                try:
                    dir_path.rmdir()
                except OSError:
                    pass

    return {
        "applied": apply,
        "scanned": len(kept) + len(purged),
        "kept": len(kept),
        "purged": len(purged),
        "purged_paths": purged,
        "errors": errors,
        "root": str(root),
    }
