#!/usr/bin/env python3
"""Regenerate wiki file-doc skeletons for every project.

The 2026-05-18 shallow-purge incident deleted 8 629 auto-generated
file-doc pages because they had under 500 chars of real prose. The
user correction was explicit: *deletion is not curation*. The right
move is to keep one skeleton per source file with EVERY missing
section visible — so the reader sees what's not yet documented and the
LLM has a concrete queue to drain.

This script:

  1. Discovers every git-tracked project under the configured dev
     roots (via ``shared.domain_mapping``).
  2. For each project + each source file, generates a wiki page at
     ``reference/<domain>/<flattened-path>.md`` via
     ``core.wiki_file_doc_skeleton.build_file_doc``.
  3. Skips files that already have a substantive page (>= 1500 chars
     of real prose) — we don't want to overwrite hand-curated work.
  4. Reports counts per project.

Usage::

    PYTHONPATH=<cortex-root> python3 scripts/regenerate_file_docs.py [--apply]

Without ``--apply`` it's a dry-run that prints what would be generated.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _flatten_source_path(rel_path: str) -> str:
    """``src/auth/login.py`` → ``src-auth-login.py`` so the slug is one segment."""
    return rel_path.replace("/", "-").replace("\\", "-")


# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_SUBSTANTIVE_PROSE_CHARS = 1500


def _existing_substantive(page_path: Path) -> bool:
    """Skip overwrite when an existing page already has real content."""
    if not page_path.is_file():
        return False
    try:
        from mcp_server.core.wiki_stub_detector import prose_char_count

        text = page_path.read_text(encoding="utf-8", errors="ignore")
        # Drop frontmatter before measuring prose.
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end >= 0:
                text = text[end + 4 :]
        return prose_char_count(text) >= _MIN_SUBSTANTIVE_PROSE_CHARS
    except (ImportError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write files (default: dry-run).",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help="Restrict to a single domain (default: all).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Cap files per domain (0 = unlimited).",
    )
    args = parser.parse_args()

    # Imports here so the script bails clean if PYTHONPATH is wrong.
    from mcp_server.core.wiki_coverage import (
        _project_source_root,
        list_source_files,
    )
    from mcp_server.core.wiki_file_doc_skeleton import build_file_doc
    from mcp_server.infrastructure.config import WIKI_ROOT
    from mcp_server.shared.domain_mapping import _build_registry

    wiki_root = Path(WIKI_ROOT).expanduser()
    today = _today()

    # Source-of-truth for "every project" is the git registry — not the
    # wiki tree. Using the wiki tree would miss every project that
    # currently has no pages (e.g. after a purge wiped empty dirs).
    registry = _build_registry()
    domains = sorted({r.canonical for r in registry.repos})
    if args.domain:
        domains = [d for d in domains if d == args.domain]
    if not domains:
        print("no domains found in registry", file=sys.stderr)
        return 2

    total_generated = 0
    total_skipped = 0
    per_domain: dict[str, tuple[int, int]] = {}

    for domain in domains:
        src_root = _project_source_root(domain)
        if src_root is None:
            print(f"  {domain}: no source root resolved — skipping")
            continue
        files = list_source_files(src_root)
        if args.max_files > 0:
            files = files[: args.max_files]
        gen = 0
        skip = 0
        for rel in files:
            page_rel = f"reference/{domain}/{_flatten_source_path(rel)}.md"
            page_path = wiki_root / page_rel
            if _existing_substantive(page_path):
                skip += 1
                continue
            try:
                src_text = (Path(src_root) / rel).read_text(
                    encoding="utf-8", errors="ignore"
                )
            except OSError:
                skip += 1
                continue
            page_body = build_file_doc(rel, src_text, domain, today=today)
            if args.apply:
                page_path.parent.mkdir(parents=True, exist_ok=True)
                page_path.write_text(page_body, encoding="utf-8")
            gen += 1
        per_domain[domain] = (gen, skip)
        total_generated += gen
        total_skipped += skip
        print(
            f"  {domain:35} src={len(files):5}  generated={gen:5}  "
            f"skipped(existing curated)={skip:4}"
        )

    print()
    print(f"total generated: {total_generated}")
    print(f"total skipped (already curated): {total_skipped}")
    if not args.apply:
        print("(dry-run — pass --apply to write files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
