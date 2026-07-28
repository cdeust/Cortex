#!/usr/bin/env python3
"""Seed ``wiki.citations`` for pages created before the flow-forward
write-path landed — M-D7, INC7.7.

Runs ``handlers.consolidation.wiki_citation_seed_pass`` against the
shared store and writes a campaign journal artifact (page_id, memory_id,
domain, reliability tier, outcome per row — the same journalisation
shape as ``memory_reheat.py``, I6-D5).

Scope (see the campaign report / ``core.wiki_citation_seed`` module
docstring for the full reliability audit): only the HIGH-reliability
source is seeded — pages whose ``wiki.pages.memory_id`` already carries
an FK-constrained pointer to their authoring memory. ``wiki.page_sources``
(file edges) and inferred tags/links are deliberately EXCLUDED — they
cannot produce a memory_id without fabricating provenance.

Usage
-----

Dry-run (default) — scan, decide, and report, write nothing::

    uv run python scripts/wiki_citation_seed.py

Apply the change to the DB::

    uv run python scripts/wiki_citation_seed.py --apply

Rollback (if ``--apply`` needs to be undone) — every row this campaign
writes is uniquely identifiable by the journal's ``(page_id, memory_id)``
pairs and by ``domain = ''`` OR any domain string this script recorded
(session_id is always ``''`` for this campaign, distinguishing it from
CITED_IN rows written by ``wiki_read``, whose partial unique index
requires ``session_id <> ''``)::

    DELETE FROM wiki.citations
    WHERE session_id = ''
      AND (page_id, memory_id) IN (<pairs from the journal artifact>);

The pass is idempotent: re-running after ``--apply`` finds every seeded
pair already in ``wiki.citations``, so ``seeded`` is 0 on immediate
re-run (confirmed by this campaign's idempotence test).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


async def _run(apply: bool, limit: int) -> dict:
    from mcp_server.handlers.consolidation.wiki_citation_seed_pass import (
        DEFAULT_SEED_SCAN_LIMIT,
        run_wiki_citation_seed_pass,
    )
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import get_shared_store

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return await run_wiki_citation_seed_pass(
        store, apply=apply, limit=limit or DEFAULT_SEED_SCAN_LIMIT
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the seeded citation rows to the DB. Default is dry-run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max candidate rows to scan in this run (default: "
        "core.wiki_citation_seed's DEFAULT_SEED_SCAN_LIMIT, 5000 — "
        "comfortably covers the known ~20-row stock).",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=None,
        help="Path to write the campaign journal JSON artifact (default: "
        "docs/campaigns/i7d7_wiki_citation_seed_<dry-run|apply>_<UTC-"
        "timestamp>.json).",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] scanning wiki.pages with memory_id set "
        f"(limit={args.limit or 'default(5000)'})",
        file=sys.stderr,
    )

    result = asyncio.run(_run(args.apply, args.limit))

    print("", file=sys.stderr)
    print("wiki.citations seed summary (M-D7, INC7.7)", file=sys.stderr)
    print("============================================", file=sys.stderr)
    print(f"  Status:                {result['status']}", file=sys.stderr)
    print(f"  Scanned rows:          {result['scanned_rows']}", file=sys.stderr)
    print(f"  Seeded:                {result['seeded']}", file=sys.stderr)
    print(f"  Already cited:         {result['already_cited']}", file=sys.stderr)
    print(f"  Skipped (race):        {result['skipped_race']}", file=sys.stderr)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    journal_path = args.journal or (
        _REPO_ROOT
        / "docs"
        / "campaigns"
        / (
            f"i7d7_wiki_citation_seed_"
            f"{'apply' if args.apply else 'dry-run'}_{timestamp}.json"
        )
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps(
            {
                "mode": mode,
                "timestamp_utc": timestamp,
                "limit": args.limit or None,
                "status": result["status"],
                "scanned_rows": result["scanned_rows"],
                "seeded": result["seeded"],
                "already_cited": result["already_cited"],
                "skipped_race": result["skipped_race"],
                "journal": result["journal"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nJournal artifact written to {journal_path}", file=sys.stderr)

    if not args.apply and result["seeded"] > 0:
        print(
            f"\nThis was a dry-run. Re-run with --apply to write "
            f"{result['seeded']} wiki.citations rows.",
            file=sys.stderr,
        )

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
