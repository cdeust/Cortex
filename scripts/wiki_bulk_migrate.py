#!/usr/bin/env python3
"""Bulk-rename the known wiki pollution patterns — Phase 4 of ADR-2244.

The 2026-05-12 audit found three deterministic-rename pollution classes
that this script targets:

  Pattern                     Audit count   Target rename
  ─────────────────────────────────────────────────────────────────────
  ``*.md.md``                 58            strip the duplicate extension
  ``*-decision-created-       10            derive slug from frontmatter
   YYYY-MM-DDtHH-MM-SSz.md``                title or first body heading
  ``*users-cdeust-... .md``   10            derive slug from frontmatter
   (path-leak in slug)                      title; reject path-shaped
                                            content

Operation per page:

  1. Read source; require a valid frontmatter ``id`` (Phase 3 invariant).
     Run ``scripts/wiki_backfill_ids.py --apply`` first if missing.
  2. Compute a clean destination path.
  3. Call the ``wiki_rename`` handler, which (a) writes the content at
     the new path, (b) replaces the old path with a redirect stub
     (path-based + id-based) so inbound links keep resolving.

Dry-run by default. ``--apply`` commits the moves. The script is
idempotent: a second ``--apply`` run finds zero pollution paths to
rename (the renames are gone; their stubs are detected and skipped).

Out of scope for this script: the 7820-page ``notes/<domain>/<id>-file-*.md``
→ ``reference/<domain>/<file-slug>.md`` re-bucket. That operation
changes the *kind directory* and needs frontmatter rewrite (kind /
provenance), not just a rename — separate Phase 4 follow-up.
"""

from __future__ import annotations

import argparse
import asyncio
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
from mcp_server.core.wiki_redirect import is_redirect, parse_frontmatter  # noqa: E402


# ── Pollution classifiers ───────────────────────────────────────────────


_DOUBLE_MD_SUFFIX = ".md.md"

# Timestamp shape found in the 10 polluted ADRs (Audit 2026-05-12):
# ``<num>-decision-created-2026-04-15t09-29-10z.md``.
_TIMESTAMP_SLUG_RE = re.compile(
    r"^(?P<prefix>\d+-)?decision-created-\d{4}-\d{2}-\d{2}t\d{2}-\d{2}-\d{2}z$",
    re.IGNORECASE,
)

# Path-leak slug shape: the slug contains an absolute filesystem path
# stripped of its leading slash (``users-cdeust-documents-developments-…``).
_PATH_LEAK_SLUG_RE = re.compile(
    r"(?:^|-)users-(?:cdeust|home|root)-"
    r"(?:documents-developments|home|opt|etc|var|tmp)-",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Pollution:
    """One detected pollution case + proposed clean path."""

    rel_path: str
    pattern: str  # "double-md" | "timestamp-slug" | "path-leak"
    proposed_path: str
    reason: str  # what to put in the redirect stub
    page_id: str | None  # None when source lacks an id
    skipped_reason: str = ""  # non-empty when we cannot rename this page


@dataclass
class Summary:
    """Counts surfaced to stdout for human review."""

    scanned: int = 0
    by_pattern: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    renamed: int = 0


# ── Slug derivation ─────────────────────────────────────────────────────


def _clean_title_candidate(title: str) -> bool:
    """True iff a title is suitable to drive a slug.

    Rejects: empty / very short / path-shaped / timestamp-shaped /
    obviously synthetic ("memory-…").
    """
    if not title or len(title.strip()) < 4:
        return False
    t = title.strip()
    if t.lower().startswith("memory-"):
        return False
    if re.search(r"/(Users|home|root|opt|var|etc|tmp)/", t, re.IGNORECASE):
        return False
    if re.search(r"\d{4}-\d{2}-\d{2}T\d{2}", t, re.IGNORECASE):
        return False
    return True


def _derive_clean_slug(
    text: str,
    fm: dict[str, object],
    fallback_prefix: str,
) -> str:
    """Pick a clean slug from frontmatter title, body H1, or a fallback.

    The fallback is ``<fallback_prefix>-<hash6>`` — used only when the
    page truly has no usable title.
    """
    title_raw = fm.get("title", "")
    title = title_raw if isinstance(title_raw, str) else ""
    if _clean_title_candidate(title):
        return slugify(title)

    # Try the first H1/H2 in the body.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") or stripped.startswith("## "):
            heading = stripped.lstrip("#").strip()
            if _clean_title_candidate(heading):
                return slugify(heading)

    # Final fallback — short hash of the body content to keep the slug stable.
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:6]
    return f"{fallback_prefix}-{digest}"


# ── Pollution detection ─────────────────────────────────────────────────


def _detect_double_md(rel_path: str) -> tuple[bool, str]:
    """``foo.md.md`` → propose ``foo.md``."""
    if not rel_path.endswith(_DOUBLE_MD_SUFFIX):
        return False, ""
    return True, rel_path[: -len(_DOUBLE_MD_SUFFIX)] + ".md"


def _stem(rel_path: str) -> str:
    """The filename stem (no directories, no .md suffix(es))."""
    name = rel_path.rsplit("/", 1)[-1]
    while name.endswith(".md"):
        name = name[:-3]
    return name


def _detect_timestamp_slug(rel_path: str) -> bool:
    return _TIMESTAMP_SLUG_RE.match(_stem(rel_path)) is not None


def _detect_path_leak_slug(rel_path: str) -> bool:
    return _PATH_LEAK_SLUG_RE.search(_stem(rel_path)) is not None


def _propose_timestamp_rename(rel_path: str, text: str, fm: dict[str, object]) -> str:
    """Compute a clean target for a timestamp-slug ADR.

    Preserves the leading numeric prefix (the ADR sequence number) when
    present, replaces the polluted tail with a content-derived slug.
    """
    stem = _stem(rel_path)
    m = _TIMESTAMP_SLUG_RE.match(stem)
    prefix = m.group("prefix") if m and m.group("prefix") else ""
    new_slug = _derive_clean_slug(text, fm, fallback_prefix="decision")
    dirname = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
    new_name = f"{prefix}{new_slug}.md"
    return f"{dirname}/{new_name}" if dirname else new_name


def _propose_path_leak_rename(rel_path: str, text: str, fm: dict[str, object]) -> str:
    """Compute a clean target for a path-leak slug page."""
    stem = _stem(rel_path)
    # Preserve a leading ``YYYY-MM-DD-`` date prefix if present (notes
    # convention).  Otherwise no prefix.
    m = re.match(r"^(\d{4}-\d{2}-\d{2}-)", stem)
    prefix = m.group(1) if m else ""
    new_slug = _derive_clean_slug(text, fm, fallback_prefix="page")
    dirname = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
    new_name = f"{prefix}{new_slug}.md"
    return f"{dirname}/{new_name}" if dirname else new_name


# ── Walk + plan ─────────────────────────────────────────────────────────


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def plan(wiki_root: Path) -> list[Pollution]:
    """Walk the wiki and return one Pollution record per detected case.

    Pages that are themselves redirect stubs are skipped. Pages that
    lack a valid frontmatter ``id`` are recorded with a non-empty
    ``skipped_reason`` so the caller can surface them without erroring.
    """
    plans: list[Pollution] = []
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if rel.parts and rel.parts[0].startswith("."):
            continue
        rel_str = str(rel)

        is_double, double_target = _detect_double_md(rel_str)
        is_timestamp = _detect_timestamp_slug(rel_str)
        is_path_leak = _detect_path_leak_slug(rel_str)
        if not (is_double or is_timestamp or is_path_leak):
            continue

        text = _read_text(md)
        if text is None:
            plans.append(
                Pollution(
                    rel_path=rel_str,
                    pattern="errored",
                    proposed_path="",
                    reason="",
                    page_id=None,
                    skipped_reason="read failed",
                )
            )
            continue

        fm = parse_frontmatter(text)
        if is_redirect(fm):
            continue  # already a stub, leave it alone

        page_id = extract_page_id(fm)
        if page_id is None:
            plans.append(
                Pollution(
                    rel_path=rel_str,
                    pattern=(
                        "double-md"
                        if is_double
                        else "timestamp-slug"
                        if is_timestamp
                        else "path-leak"
                    ),
                    proposed_path="",
                    reason="",
                    page_id=None,
                    skipped_reason="missing frontmatter id — run wiki_backfill_ids.py first",
                )
            )
            continue

        if is_double:
            plans.append(
                Pollution(
                    rel_path=rel_str,
                    pattern="double-md",
                    proposed_path=double_target,
                    reason="strip .md.md duplicate extension",
                    page_id=page_id,
                )
            )
        elif is_timestamp:
            plans.append(
                Pollution(
                    rel_path=rel_str,
                    pattern="timestamp-slug",
                    proposed_path=_propose_timestamp_rename(rel_str, text, fm),
                    reason="replace timestamp-as-slug with content-derived slug",
                    page_id=page_id,
                )
            )
        else:  # is_path_leak
            plans.append(
                Pollution(
                    rel_path=rel_str,
                    pattern="path-leak",
                    proposed_path=_propose_path_leak_rename(rel_str, text, fm),
                    reason="remove filesystem path leaked into slug",
                    page_id=page_id,
                )
            )
    return plans


# ── Apply (delegates to wiki_rename handler) ────────────────────────────


async def _apply_plan(
    plan_items: list[Pollution],
    wiki_root: Path,
) -> tuple[int, list[str]]:
    """Run each non-skipped item through the wiki_rename handler.

    Returns (renamed_count, error_messages). The handler is patched to
    use ``wiki_root`` rather than the configured WIKI_ROOT so this
    function is testable against a tmp_path.
    """
    # Local import keeps test fixtures lightweight when --apply isn't used.
    from mcp_server.handlers import wiki_rename

    # Point the handler at our wiki_root.
    original = wiki_rename.WIKI_ROOT
    wiki_rename.WIKI_ROOT = str(wiki_root)

    renamed = 0
    errors: list[str] = []
    try:
        for item in plan_items:
            if item.skipped_reason:
                continue
            if not item.proposed_path:
                continue
            result = await wiki_rename.handler(
                {
                    "from_path": item.rel_path,
                    "to_path": item.proposed_path,
                    "reason": item.reason,
                }
            )
            if "error" in result:
                errors.append(f"{item.rel_path}: {result['error']}")
            else:
                renamed += 1
    finally:
        wiki_rename.WIKI_ROOT = original
    return renamed, errors


def summarize(plans: list[Pollution]) -> Summary:
    summary = Summary()
    summary.scanned = len(plans)
    for item in plans:
        if item.skipped_reason:
            summary.skipped[item.skipped_reason] = (
                summary.skipped.get(item.skipped_reason, 0) + 1
            )
            continue
        summary.by_pattern[item.pattern] = summary.by_pattern.get(item.pattern, 0) + 1
    return summary


def _print_summary(summary: Summary, *, applied: bool) -> None:
    print("", file=sys.stderr)
    print("Wiki bulk-migration plan", file=sys.stderr)
    print("========================", file=sys.stderr)
    print(f"  Pollution paths detected: {summary.scanned}", file=sys.stderr)
    for pattern, n in sorted(summary.by_pattern.items()):
        print(f"    - {pattern:18s} {n}", file=sys.stderr)
    if summary.skipped:
        print("  Skipped:", file=sys.stderr)
        for reason, n in sorted(summary.skipped.items()):
            print(f"    - {reason:60s} {n}", file=sys.stderr)
    if applied:
        print(f"  Renamed (applied): {summary.renamed}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wiki",
        type=Path,
        default=Path.home() / ".claude" / "methodology" / "wiki",
        help="Wiki root directory.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the renames in place. Default is dry-run.",
    )
    args = parser.parse_args()

    wiki_root: Path = args.wiki.expanduser().resolve()
    if not wiki_root.is_dir():
        print(f"error: wiki root not found: {wiki_root}", file=sys.stderr)
        return 2

    print(
        f"[{'APPLY' if args.apply else 'DRY-RUN'}] scanning {wiki_root}",
        file=sys.stderr,
    )
    plans = plan(wiki_root)
    summary = summarize(plans)

    if args.apply:
        renamed, errors = asyncio.run(_apply_plan(plans, wiki_root))
        summary.renamed = renamed
        _print_summary(summary, applied=True)
        if errors:
            print("", file=sys.stderr)
            print(f"  Rename errors ({len(errors)}):", file=sys.stderr)
            for err in errors[:20]:
                print(f"    {err}", file=sys.stderr)
            return 1
        return 0

    _print_summary(summary, applied=False)
    # Show the first 10 proposed renames so a human can spot-check.
    proposed = [p for p in plans if not p.skipped_reason]
    if proposed:
        print("", file=sys.stderr)
        print("  Proposed renames (first 10):", file=sys.stderr)
        for item in proposed[:10]:
            print(f"    {item.rel_path}", file=sys.stderr)
            print(f"    → {item.proposed_path}", file=sys.stderr)
            print(f"      ({item.pattern}: {item.reason})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
