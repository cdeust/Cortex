#!/usr/bin/env python3
"""Collapse active memories with byte-identical content onto their
hottest member via supersession — I6-D1, INC6.3.

Runs ``handlers.consolidation.memory_dedup_exact_pass`` against the
shared store and writes a campaign journal artifact (dup_key, elected
survivor, superseded ids, group size, observed domains per group — the
same "journalisation" shape as ``memory_domain_backfill.py``, I6-D3).

Usage
-----

Dry-run (default) — group, elect, and report, write nothing::

    uv run python scripts/memory_dedup_exact.py

Apply the change to the DB::

    uv run python scripts/memory_dedup_exact.py --apply

The pass is idempotent: re-running after ``--apply`` finds zero groups
left to collapse (``current_memories`` no longer contains the superseded
rows, so the grouping query returns nothing for them), and never
supersedes a row that is not still an open chain head at write time
(``pg_store_memory_dedup.supersede_to_existing``'s CAS guard).
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
from mcp_server.handlers.consolidation.memory_dedup_exact_pass import (  # noqa: E402
    run_memory_dedup_exact_pass,
)
from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: E402
from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: E402


async def _run(apply: bool, limit: int) -> dict:

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return await run_memory_dedup_exact_pass(store, apply=apply, limit=limit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the supersession edges to the DB. Default is dry-run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Max duplicate-group MEMBER ROWS to scan in this run "
        "(default 5000, comfortably covers the known ~146-row stock).",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=None,
        help="Path to write the campaign journal JSON artifact (default: "
        "docs/campaigns/i6d1_memory_dedup_exact_<dry-run|apply>_<UTC-timestamp>.json).",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] scanning active exact-duplicate groups (limit={args.limit})",
        file=sys.stderr,
    )

    result = asyncio.run(_run(args.apply, args.limit))

    print("", file=sys.stderr)
    print("Memory exact-dedup summary (I6-D1)", file=sys.stderr)
    print("===================================", file=sys.stderr)
    print(f"  Status:                {result['status']}", file=sys.stderr)
    print(f"  Scanned rows:          {result['scanned_rows']}", file=sys.stderr)
    print(f"  Groups collapsed:      {result['groups']}", file=sys.stderr)
    print(f"  Superseded edges:      {result['superseded_total']}", file=sys.stderr)
    print(f"  Skipped (race/CAS):    {result['skipped_race']}", file=sys.stderr)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    journal_path = args.journal or (
        _REPO_ROOT
        / "docs"
        / "campaigns"
        / (
            f"i6d1_memory_dedup_exact_"
            f"{'apply' if args.apply else 'dry-run'}_{timestamp}.json"
        )
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps(
            {
                "mode": mode,
                "timestamp_utc": timestamp,
                "limit": args.limit,
                "status": result["status"],
                "scanned_rows": result["scanned_rows"],
                "groups": result["groups"],
                "superseded_total": result["superseded_total"],
                "skipped_race": result["skipped_race"],
                "journal": result["journal"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nJournal artifact written to {journal_path}", file=sys.stderr)

    if not args.apply and result["groups"] > 0:
        print(
            f"\nThis was a dry-run. Re-run with --apply to write "
            f"{result['superseded_total']} supersession edges across "
            f"{result['groups']} groups.",
            file=sys.stderr,
        )

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
