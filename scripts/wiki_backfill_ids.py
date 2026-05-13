#!/usr/bin/env python3
"""Backfill stable page IDs on every existing wiki page — Phase 3 of ADR-2244.

Walks the methodology wiki and, for each page that lacks a valid
``id`` field in its frontmatter, mints a fresh UUID4 and writes it back
in place. The page body and other frontmatter fields are preserved
verbatim.

Goal: every page has a stable identifier *before* Phase 4 bulk migration
moves pages around. Without it, inbound links into renamed pages rot.
With it, renames can leave redirect stubs (see
``mcp_server.core.wiki_redirect``).

Usage
-----

Dry-run (default) — show counts and a sample of paths::

    python scripts/wiki_backfill_ids.py

Apply the change in place::

    python scripts/wiki_backfill_ids.py --apply

The script is idempotent: re-running after ``--apply`` finds zero
pages needing a backfill (all already have ids). Pages that already
carry a valid ``id`` are skipped, no exceptions. Redirect stub pages
(``redirect_to`` / ``redirect_id`` in frontmatter) are skipped — they
don't need their own identity, they reference another page's.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure mcp_server is importable when run from the Cortex repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_server.core.wiki_identity import (  # noqa: E402
    ensure_page_id,
    extract_page_id,
)
from mcp_server.core.wiki_redirect import is_redirect, parse_frontmatter  # noqa: E402


@dataclass(frozen=True)
class BackfillSummary:
    """Aggregate counts from a backfill run."""

    scanned: int
    already_has_id: int
    minted: int
    skipped_redirects: int
    skipped_no_frontmatter: int
    errored: int


def _has_frontmatter(text: str) -> bool:
    return text.startswith("---")


_EXISTING_ID_LINE = re.compile(r"^id:\s*\S.*$", re.MULTILINE)


def _insert_id_into_frontmatter(text: str, page_id: str) -> str:
    """Add or replace ``id: <page_id>`` inside the frontmatter block.

    Preconditions: ``text`` begins with ``---`` delimited frontmatter.

    Behavior:
      - If an ``id:`` line exists *inside the frontmatter*, replace its
        value with ``page_id``. This handles the malformed-id case
        (e.g. ``id: garbage``) — we overwrite the bad value rather than
        leaving a duplicate key.
      - Otherwise insert ``id: <page_id>`` immediately after the opening
        ``---`` line.

    The body (everything after the closing fence) is untouched.
    """
    head_end = text.find("\n")
    if head_end == -1:
        return text
    fm_close = text.find("\n---", head_end)
    if fm_close == -1:
        # Malformed frontmatter (no closing fence) — fall back to insert.
        return text[: head_end + 1] + f"id: {page_id}\n" + text[head_end + 1 :]

    fm_block = text[head_end + 1 : fm_close + 1]
    new_line = f"id: {page_id}"
    if _EXISTING_ID_LINE.search(fm_block):
        new_fm_block = _EXISTING_ID_LINE.sub(new_line, fm_block, count=1)
        return text[: head_end + 1] + new_fm_block + text[fm_close + 1 :]
    return text[: head_end + 1] + new_line + "\n" + text[head_end + 1 :]


def _process_file(
    path: Path,
    apply: bool,
) -> str:
    """Return a per-file status string.

    Status values:
      - ``minted``         — id added (or would be, in dry-run)
      - ``has_id``         — already had a valid id
      - ``redirect``       — stub page, no id needed
      - ``no_frontmatter`` — page lacks any frontmatter, skipped
      - ``errored``        — io / parse failure
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "errored"

    if not _has_frontmatter(text):
        return "no_frontmatter"

    fm = parse_frontmatter(text)
    if is_redirect(fm):
        return "redirect"

    existing = extract_page_id(fm)
    if existing is not None:
        return "has_id"

    page_id, minted = ensure_page_id(fm)
    if not minted:
        # Should be unreachable: extract returned None so ensure must mint.
        return "has_id"

    if apply:
        new_text = _insert_id_into_frontmatter(text, page_id)
        try:
            path.write_text(new_text, encoding="utf-8")
        except OSError:
            return "errored"
    return "minted"


def run(
    wiki_root: Path,
    *,
    apply: bool,
) -> BackfillSummary:
    """Walk the wiki, mint ids on pages that lack them. Returns the summary."""
    counts: dict[str, int] = {
        "scanned": 0,
        "minted": 0,
        "has_id": 0,
        "redirect": 0,
        "no_frontmatter": 0,
        "errored": 0,
    }
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if rel.parts and rel.parts[0].startswith("."):
            continue  # skip .generated/ etc.
        counts["scanned"] += 1
        status = _process_file(md, apply)
        counts[status] = counts.get(status, 0) + 1

    return BackfillSummary(
        scanned=counts["scanned"],
        already_has_id=counts["has_id"],
        minted=counts["minted"],
        skipped_redirects=counts["redirect"],
        skipped_no_frontmatter=counts["no_frontmatter"],
        errored=counts["errored"],
    )


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
        help="Write the new ids in place. Default is dry-run.",
    )
    args = parser.parse_args()

    wiki_root: Path = args.wiki.expanduser().resolve()
    if not wiki_root.is_dir():
        print(f"error: wiki root not found: {wiki_root}", file=sys.stderr)
        return 2

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] scanning {wiki_root}", file=sys.stderr)
    summary = run(wiki_root, apply=args.apply)

    print("", file=sys.stderr)
    print("Wiki page-ID backfill summary", file=sys.stderr)
    print("=============================", file=sys.stderr)
    print(f"  Scanned:                {summary.scanned}", file=sys.stderr)
    print(f"  Already had id:         {summary.already_has_id}", file=sys.stderr)
    print(
        f"  {'Minted (applied)' if args.apply else 'Would mint'}:"
        f"        {summary.minted}",
        file=sys.stderr,
    )
    print(f"  Skipped (redirect):     {summary.skipped_redirects}", file=sys.stderr)
    print(
        f"  Skipped (no fm):        {summary.skipped_no_frontmatter}", file=sys.stderr
    )
    print(f"  Errored:                {summary.errored}", file=sys.stderr)

    if not args.apply and summary.minted > 0:
        print(
            f"\nThis was a dry-run. Re-run with --apply to write {summary.minted}"
            " ids back to disk.",
            file=sys.stderr,
        )

    return 0 if summary.errored == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
