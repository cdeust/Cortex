"""Handler: wiki_purge — remove wiki pages that fail the current classifier.

Re-evaluates every authored wiki page against the current classifier rules
and deletes the ones that would no longer be admitted. Memories in the
PostgreSQL/SQLite store are left untouched — only the markdown files in
~/.claude/methodology/wiki/ are removed.

source: ADR-0465"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.core.wiki_classifier import classify_memory
from mcp_server.core.wiki_stub_detector import (
    DEFAULT_SHALLOW_THRESHOLD,
    DEFAULT_STUB_THRESHOLD,
    is_shallow,
    is_stub,
    placeholder_count,
    stub_score,
)
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.shared.yaml_parser import parse_yaml_frontmatter
from mcp_server.handlers._tool_meta import DESTRUCTIVE

# ── Schema ─────────────────────────────────────────────────────────────

schema = {
    "title": "Wiki — purge stale",
    "annotations": DESTRUCTIVE,
    "description": (
        "Purge wiki pages that no longer earn their place. Two reject "
        "axes: (1) the page no longer passes the current classifier "
        "(`core/wiki_classifier`) — used after tightening rules or a "
        "polluting backfill; (2) the page is a stub — body is majority "
        "placeholder markers (_(to be filled)_ / _To be written._ / "
        "_(none identified)_), produced by the groomer or by "
        "template_v1 synthesis. Stubs masquerade as content but carry "
        "none. Memories remain in the store (still surface via "
        "`recall`); only the wiki markdown files are removed from "
        "disk. Distinct from `wiki_consolidate` (heat decay + "
        "lifecycle, doesn't delete based on classifier), `forget` "
        "(deletes a memory, not a wiki page), and `wiki_compile` "
        "(publishes drafts, doesn't purge). Defaults to dry-run; pass "
        "apply=true to actually delete. Latency ~200-500ms. Returns "
        "{kept, purged, purged_paths, purged_reasons, dry_run}."
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
            "purge_stubs": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Purge pages whose body is majority placeholder "
                    "markers. The dominant noise source today — disable "
                    "only when you want to inspect classifier-purges in "
                    "isolation."
                ),
            },
            "purge_classifier_rejects": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Purge pages that the current classifier no longer "
                    "admits. Set false when you only want to clean stubs "
                    "without re-running the classifier."
                ),
            },
            "stub_threshold": {
                "type": "number",
                "default": DEFAULT_STUB_THRESHOLD,
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    # source: ADR-0465
                    "Fraction of content lines that must be placeholder markers for "
                    "stub classification. Default 0.5; lower values also match "
                    "mixed-content pages."
                ),
            },
            "max_purges": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Cap on how many pages this invocation may delete. "
                    "Acts as a safety rail against a buggy classifier "
                    "change wiping the whole wiki in one shot — pages "
                    "beyond the cap stay on disk and surface again on "
                    "the next call so cleanup proceeds gradually. Omit "
                    "(or pass 0) to disable the cap; callers in "
                    "autonomous mode (`consolidate`) supply a small "
                    "value, one-shot human sweeps pass 0 to remove all."
                ),
            },
            "purge_shallow": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Purge pages whose body has fewer than "
                    "`shallow_threshold` prose chars — typically "
                    "auto-generated file-doc dumps that carry only "
                    "metadata and import lists, no actual "
                    "explanation. These take space and mislead readers."
                ),
            },
            "shallow_threshold": {
                "type": "integer",
                "default": DEFAULT_SHALLOW_THRESHOLD,
                "minimum": 0,
                "description": (
                    "Minimum prose-char count a page must carry to "
                    "escape the shallow filter. Default 500; pages "
                    "below this are flagged."
                ),
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


def _evaluate_page(
    md_path: Path,
    *,
    check_classifier: bool,
    check_stub: bool,
    check_shallow: bool,
    stub_threshold: float,
    shallow_threshold: int,
) -> tuple[str | None, list[str], str | None, float]:
    """Evaluate a page against the configured reject axes.

    Three axes, checked in order — stub first (cheapest, unambiguous),
    shallow next (auto-gen file dumps), classifier last (most expensive).

      * ``stub`` — body is majority placeholder markers.
      * ``shallow`` — body has too few prose chars to be an explanation.
      * ``classifier_reject`` — classifier no longer admits the content.
    """
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    r = parse_yaml_frontmatter(text)
    tags = _parse_tags(r.meta.get("tags"))
    body = r.body or ""
    score = stub_score(body)

    if check_stub and is_stub(body, threshold=stub_threshold):
        return None, tags, "stub", score

    if check_shallow and is_shallow(body, threshold=shallow_threshold):
        return None, tags, "shallow", score

    if check_classifier:
        lines = body.strip().splitlines()
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        content = "\n".join(lines).strip() or str(r.meta.get("title", ""))
        result = classify_memory(content, tags)
        kind = result.kind if result is not None else None
        if kind is None:
            return None, tags, "classifier_reject", score
        return kind, tags, None, score

    # No axis fired — keep the page (use this for stat-only runs).
    return "_unchecked", tags, None, score


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Purge wiki pages that no longer earn their place."""
    args = args or {}
    apply = bool(args.get("apply", False))
    kind_filter = args.get("kind")
    purge_stubs = bool(args.get("purge_stubs", True))
    purge_classifier_rejects = bool(args.get("purge_classifier_rejects", True))
    purge_shallow = bool(args.get("purge_shallow", True))
    threshold = float(args.get("stub_threshold") or DEFAULT_STUB_THRESHOLD)
    shallow_thresh = int(args.get("shallow_threshold") or DEFAULT_SHALLOW_THRESHOLD)
    max_purges_raw = args.get("max_purges")
    max_purges = (
        int(max_purges_raw)
        if max_purges_raw is not None and int(max_purges_raw) > 0
        else None
    )

    root = Path(WIKI_ROOT).expanduser()
    if not root.exists():
        return {"error": f"wiki root does not exist: {root}"}

    target_dirs = {kind_filter} if kind_filter else _PAGE_DIRS
    kept: list[str] = []
    purged: list[str] = []
    deferred: list[str] = []
    purged_reasons: dict[str, int] = {"stub": 0, "shallow": 0, "classifier_reject": 0}
    placeholder_lines_purged = 0
    errors: list[str] = []
    cap_reached = False

    for md in root.rglob("*.md"):
        rel = md.relative_to(root)
        if rel.parts[0] not in target_dirs:
            continue
        try:
            _, _tags, reason, _ = _evaluate_page(
                md,
                check_classifier=purge_classifier_rejects,
                check_stub=purge_stubs,
                check_shallow=purge_shallow,
                stub_threshold=threshold,
                shallow_threshold=shallow_thresh,
            )
            if reason is not None:
                # Cap applies only when ``apply`` is True — dry-run reports
                # the full count so operators see the actual backlog.
                if apply and max_purges is not None and len(purged) >= max_purges:
                    deferred.append(str(rel))
                    cap_reached = True
                    continue
                purged.append(str(rel))
                purged_reasons[reason] = purged_reasons.get(reason, 0) + 1
                if reason == "stub":
                    placeholder_lines_purged += placeholder_count(
                        md.read_text(encoding="utf-8", errors="ignore")
                    )
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
        "scanned": len(kept) + len(purged) + len(deferred),
        "kept": len(kept),
        "purged": len(purged),
        "purged_paths": purged,
        "purged_reasons": purged_reasons,
        "deferred": len(deferred),
        "deferred_paths": deferred[:50],  # sample only — full count is the metric
        "cap_reached": cap_reached,
        "max_purges": max_purges,
        "placeholder_lines_purged": placeholder_lines_purged,
        "errors": errors,
        "root": str(root),
    }
