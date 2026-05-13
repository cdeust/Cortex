#!/usr/bin/env python3
"""Re-bucket file-documentation notes — Phase 4.2 of ADR-2244.

The 2026-05-12 audit found that ``codebase_analyze`` had been writing
per-file documentation pages under ``notes/<domain>/<memory_id>-file-
<file-slug>.md`` instead of the correct ``reference/<domain>/<file-slug>.md``.
The misroute was fixed at the producer in #27 (Task #8) but the
existing pages were never re-bucketed.

Live count on the wiki: **8,734** file-doc notes across 10 domains.
This script moves them to ``reference/`` with:

  * A clean ``<file-slug>.md`` derived from the ``file:`` frontmatter
    tag (which preserves the original source-tree path even when the
    on-disk filename was truncated).
  * Frontmatter rewritten to the modern schema:
        kind: reference
        lifecycle: seedling
        audience: [developer]
        provenance: auto-generated
        generator:
          model: cortex-codebase-analyze
          version: v1
          prompt_template: file-doc-v1
          generated_at: <ISO-8601 from the original ``created`` field>
  * A redirect stub at the original ``notes/`` path so inbound links
    keep resolving via ``wiki_read``.

Dry-run by default; ``--apply`` commits.

Idempotency
-----------

A second --apply finds zero pages to re-bucket: the originals are now
redirect stubs (skipped), and any new ``codebase_analyze`` output
already lands in ``reference/`` directly thanks to #27. The script
also skips pages whose target path already exists (collision).

Requires
--------

Each source page must carry a stable frontmatter ``id`` from Phase 3
(``scripts/wiki_backfill_ids.py --apply``). Pages without an id are
reported and skipped — the source classifier from #27 always emits an
id on new writes, but the existing population predates that.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Ensure mcp_server is importable when run from the Cortex repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_server.core.wiki_identity import extract_page_id  # noqa: E402
from mcp_server.core.wiki_layout import slugify  # noqa: E402
from mcp_server.core.wiki_redirect import (  # noqa: E402
    build_redirect_stub,
    is_redirect,
    parse_frontmatter,
)


_FILE_TAG_RE = re.compile(r"file:([^\s,]+)")
_FILE_NOTE_PATH_RE = re.compile(r"^notes/(?P<domain>[^/]+)/\d+-file-")


@dataclass(frozen=True)
class FileDocMove:
    """One detected file-doc page + computed re-bucket target."""

    rel_path: str  # current ``notes/<domain>/<id>-file-...md`` path
    target_path: str  # ``reference/<domain>/<slug>.md``
    page_id: str | None  # stable id from frontmatter, None if absent
    source_file_path: str  # original code path from the ``file:`` tag
    skip_reason: str = ""


@dataclass
class Summary:
    scanned: int = 0
    planned: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    moved: int = 0
    errors: list[str] = field(default_factory=list)


# ── Detection + slug derivation ────────────────────────────────────────


def _extract_file_tag(fm: dict[str, object]) -> str:
    """Return the original source path from the ``file:<path>`` tag.

    The tag is the canonical source-of-truth even when the on-disk
    filename has been truncated (``98817-file-....md``).
    """
    raw_tags = fm.get("tags", [])
    if isinstance(raw_tags, list):
        candidates = [str(t) for t in raw_tags]
    elif isinstance(raw_tags, str):
        candidates = [raw_tags]
    else:
        return ""
    for tag in candidates:
        m = _FILE_TAG_RE.search(tag)
        if m:
            return m.group(1).strip()
    return ""


def _derive_target_path(domain: str, source_file_path: str) -> str:
    """Compute ``reference/<domain>/<file-slug>.md``.

    The slug is a slugify of the source path with directory separators
    replaced by hyphens, so ``hooks/codebase_hook.py`` becomes
    ``hooks-codebase_hook.py`` → ``hooks-codebase_hook.py`` (the wiki
    slugify preserves underscores and the .py).
    """
    if not source_file_path:
        return ""
    # Replace path separators so the slug is a single token, then run
    # through the canonical slugify which strips trailing .md but keeps
    # other extensions (.py / .ts / etc.) — see wiki_layout.slugify.
    flat = source_file_path.replace("/", "-").replace("\\", "-")
    slug = slugify(flat)
    if not slug or slug == "unknown":
        return ""
    # ``slugify("")`` returns ``"unknown"`` so an empty domain would route
    # to ``reference/unknown/…``. Coerce to ``_general`` explicitly.
    domain_slug = slugify(domain) if domain.strip() else "_general"
    if domain_slug == "unknown":
        domain_slug = "_general"
    return f"reference/{domain_slug}/{slug}.md"


def _is_file_doc_path(rel_path: str) -> str | None:
    """Return the domain when ``rel_path`` matches the file-doc shape, else None."""
    m = _FILE_NOTE_PATH_RE.match(rel_path)
    return m.group("domain") if m else None


# ── Frontmatter rewrite ────────────────────────────────────────────────


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<fm>.*?)\n---\s*\n?", re.DOTALL)


def _strip_frontmatter(text: str) -> tuple[str, str]:
    """Split ``---\\n…\\n---\\n`` block from the body. Returns (fm_block, body)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return "", text
    return m.group("fm"), text[m.end() :]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rewrite_frontmatter(
    fm: dict[str, object],
    body: str,
    *,
    source_file_path: str,
) -> str:
    """Build the modern ``kind: reference`` frontmatter and append body.

    Preserves: id, title, tags, created, updated, memory_id (when present).
    Replaces: kind. Adds: lifecycle, audience, provenance, generator.
    """
    lines = ["---"]
    if "id" in fm:
        lines.append(f"id: {fm['id']}")
    lines.append("kind: reference")
    lines.append("lifecycle: seedling")
    lines.append("audience:")
    lines.append("  - developer")
    lines.append("provenance: auto-generated")
    lines.append("generator:")
    lines.append("  model: cortex-codebase-analyze")
    lines.append("  version: v1")
    lines.append("  prompt_template: file-doc-v1")
    lines.append(f"  generated_at: {fm.get('created', _now_iso())}")
    if "title" in fm:
        lines.append(f"title: {fm['title']}")
    if "created" in fm:
        lines.append(f"created: {fm['created']}")
    lines.append(f"updated: {_now_iso()}")
    if "memory_id" in fm:
        lines.append(f"memory_id: {fm['memory_id']}")
    # Tags pass through (block list form).
    raw_tags = fm.get("tags")
    if isinstance(raw_tags, list) and raw_tags:
        lines.append("tags:")
        for t in raw_tags:
            lines.append(f"  - {t}")
    elif isinstance(raw_tags, str) and raw_tags:
        lines.append(f"tags: {raw_tags}")
    # Trace fields for migration audit.
    lines.append(f"source_file_path: {source_file_path}")
    lines.append("rebucketed_from: notes/")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + body.lstrip("\n")


# ── Walk + plan ────────────────────────────────────────────────────────


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def plan(wiki_root: Path) -> list[FileDocMove]:
    """Walk the wiki and return one FileDocMove per file-doc note found."""
    moves: list[FileDocMove] = []
    seen_targets: set[str] = set()

    for md in (wiki_root / "notes").rglob("*-file-*.md"):
        rel = md.relative_to(wiki_root)
        rel_str = str(rel)
        domain = _is_file_doc_path(rel_str)
        if domain is None:
            continue

        text = _read_text(md)
        if text is None:
            moves.append(
                FileDocMove(
                    rel_path=rel_str,
                    target_path="",
                    page_id=None,
                    source_file_path="",
                    skip_reason="read failed",
                )
            )
            continue
        fm = parse_frontmatter(text)
        if is_redirect(fm):
            continue  # already migrated

        page_id = extract_page_id(fm)
        source_file_path = _extract_file_tag(fm)

        if page_id is None:
            moves.append(
                FileDocMove(
                    rel_path=rel_str,
                    target_path="",
                    page_id=None,
                    source_file_path=source_file_path,
                    skip_reason="missing frontmatter id — run wiki_backfill_ids.py first",
                )
            )
            continue
        if not source_file_path:
            moves.append(
                FileDocMove(
                    rel_path=rel_str,
                    target_path="",
                    page_id=page_id,
                    source_file_path="",
                    skip_reason="missing ``file:<path>`` tag",
                )
            )
            continue

        target = _derive_target_path(domain, source_file_path)
        if not target:
            moves.append(
                FileDocMove(
                    rel_path=rel_str,
                    target_path="",
                    page_id=page_id,
                    source_file_path=source_file_path,
                    skip_reason="empty slug from file tag",
                )
            )
            continue

        # Slug collision: two notes documenting the same source file.
        # Disambiguate by appending the memory id from the source's slug.
        if target in seen_targets:
            target = _disambiguate(target, rel_str)
        seen_targets.add(target)

        moves.append(
            FileDocMove(
                rel_path=rel_str,
                target_path=target,
                page_id=page_id,
                source_file_path=source_file_path,
            )
        )
    return moves


def _disambiguate(target: str, src_path: str) -> str:
    """Append the source memory id to disambiguate slug collisions."""
    m = re.search(r"/(\d+)-file-", src_path)
    suffix = m.group(1) if m else "x"
    base, ext = target.rsplit(".", 1) if "." in target else (target, "md")
    return f"{base}-{suffix}.{ext}"


# ── Apply ──────────────────────────────────────────────────────────────


def apply(wiki_root: Path, moves: list[FileDocMove]) -> tuple[int, list[str]]:
    """Execute the planned moves; return (moved_count, error_messages)."""
    moved = 0
    errors: list[str] = []

    for item in moves:
        if item.skip_reason or not item.target_path:
            continue

        src_path = wiki_root / item.rel_path
        dest_path = wiki_root / item.target_path

        if dest_path.exists():
            errors.append(
                f"{item.rel_path}: destination already exists ({item.target_path})"
            )
            continue

        text = _read_text(src_path)
        if text is None:
            errors.append(f"{item.rel_path}: read failed")
            continue
        fm_block, body = _strip_frontmatter(text)
        fm = parse_frontmatter(text)

        new_content = _rewrite_frontmatter(
            fm, body, source_file_path=item.source_file_path
        )

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            errors.append(f"{item.rel_path}: dest write failed: {exc}")
            continue

        stub_md = build_redirect_stub(
            target_path=item.target_path,
            target_id=item.page_id if item.page_id else None,
            target_title=str(fm.get("title", "")).strip(),
            reason="Phase 4.2: file-doc re-bucket to reference/",
            created_at=_now_iso(),
        )
        try:
            src_path.write_text(stub_md, encoding="utf-8")
        except OSError as exc:
            errors.append(
                f"{item.rel_path}: stub write failed: {exc} "
                f"(dest exists at {item.target_path})"
            )
            continue

        moved += 1
    return moved, errors


def summarize(moves: list[FileDocMove]) -> Summary:
    s = Summary()
    s.scanned = len(moves)
    for m in moves:
        if m.skip_reason:
            s.skipped[m.skip_reason] = s.skipped.get(m.skip_reason, 0) + 1
        else:
            s.planned += 1
    return s


def _print_summary(s: Summary, *, applied: bool) -> None:
    print("", file=sys.stderr)
    print("Wiki file-doc re-bucket plan (Phase 4.2)", file=sys.stderr)
    print("========================================", file=sys.stderr)
    print(f"  Detected file-doc pages: {s.scanned}", file=sys.stderr)
    print(f"  Plan: re-bucket           {s.planned}", file=sys.stderr)
    if s.skipped:
        print("  Skipped:", file=sys.stderr)
        for reason, n in sorted(s.skipped.items(), key=lambda kv: -kv[1]):
            print(f"    - {reason:60s} {n}", file=sys.stderr)
    if applied:
        print(f"  Moved (applied):         {s.moved}", file=sys.stderr)
        if s.errors:
            print(f"  Errors ({len(s.errors)}):", file=sys.stderr)
            for err in s.errors[:20]:
                print(f"    {err}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wiki",
        type=Path,
        default=Path.home() / ".claude" / "methodology" / "wiki",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the moves in place. Default is dry-run.",
    )
    args = parser.parse_args()

    wiki_root = args.wiki.expanduser().resolve()
    if not wiki_root.is_dir():
        print(f"error: wiki root not found: {wiki_root}", file=sys.stderr)
        return 2

    print(
        f"[{'APPLY' if args.apply else 'DRY-RUN'}] scanning {wiki_root}/notes/ for "
        f"file-doc pages",
        file=sys.stderr,
    )
    moves = plan(wiki_root)
    summary = summarize(moves)

    if args.apply:
        moved, errors = apply(wiki_root, moves)
        summary.moved = moved
        summary.errors = errors
        _print_summary(summary, applied=True)
        return 0 if not errors else 1

    _print_summary(summary, applied=False)
    if summary.planned > 0:
        print("", file=sys.stderr)
        print("  Sample re-buckets (first 5):", file=sys.stderr)
        plannable = [m for m in moves if not m.skip_reason][:5]
        for m in plannable:
            print(f"    {m.rel_path}", file=sys.stderr)
            print(f"    → {m.target_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
