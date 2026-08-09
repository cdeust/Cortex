#!/usr/bin/env python3
"""One-shot historical migration: reclassify ``memories.write_class`` rows
still at the schema migration's DEFAULT sentinel — M-D2, 7.4.

Runs ``handlers.consolidation.write_class_backfill_pass`` against the
shared store and writes a campaign journal artifact (source, from-class,
to-class, row count per reclassified group).

Precondition: the schema migration
(``infrastructure/pg_schema.py`` MIGRATIONS_DDL, ``ALTER TABLE memories
ADD COLUMN write_class ... DEFAULT 'deliberate'``) has already run against
this database — every row got the sentinel; this script is what actually
reclassifies the auto/derived/mechanical ones from their ``source`` value
(the same single choke point every writer classifies through,
``mcp_server.shared.write_class.classify_write_class``).

Usage
-----

Dry-run (default) — classify and report, write nothing::

    uv run python scripts/backfill_write_class.py

Apply the change to the DB::

    uv run python scripts/backfill_write_class.py --apply

The pass is idempotent: re-running after ``--apply`` finds zero source
groups left to reclassify (``list_source_groups_at_default`` only returns
groups still at the sentinel), and never touches a row a post-7.4 writer
already classified explicitly to something other than ``deliberate``
(the SQL UPDATE re-guards ``write_class = 'deliberate'`` at write time,
not just at scan time — see ``pg_store_memory_write_class.py``).

Known residual risk (documented, not silently assumed away): a row
explicitly written as ``write_class='deliberate'`` via a source string
this module's taxonomy maps to a DIFFERENT class (e.g. an operator
deliberately overriding a `post_tool_capture`-sourced write to
`deliberate`) is indistinguishable from an unclassified historical row
and WILL be reclassified by this pass. Bounded to the window between the
schema migration landing and this script's first run — run this script
promptly after deploying the migration to minimize it.
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
from mcp_server.handlers.consolidation.write_class_backfill_pass import (  # noqa: E402
    run_write_class_backfill_pass,
)
from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: E402
from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: E402


async def _run(apply: bool, limit: int) -> dict:

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return await run_write_class_backfill_pass(store, apply=apply, limit=limit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the reclassified write_class values to the DB. Default is dry-run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Max DISTINCT source groups to scan in this run (default 5000 "
        "— measured source cardinality across the taxonomy is in the low "
        "thousands; a single group's UPDATE touches all its rows at once).",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=None,
        help="Path to write the campaign journal JSON artifact (default: "
        "scratchpad/backfill_write_class_<dry-run|apply>_<UTC-timestamp>.json).",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] scanning memories.write_class still at the migration "
        f"DEFAULT (limit={args.limit} source groups)",
        file=sys.stderr,
    )

    result = asyncio.run(_run(args.apply, args.limit))

    print("", file=sys.stderr)
    print("write_class backfill summary (M-D2, 7.4)", file=sys.stderr)
    print("=========================================", file=sys.stderr)
    print(f"  Status:               {result['status']}", file=sys.stderr)
    print(f"  Source groups scanned: {result['scanned_groups']}", file=sys.stderr)
    print(f"  Unchanged (deliberate): {result['unchanged_groups']}", file=sys.stderr)
    print(f"  Reclassified groups:   {result['reclassified_groups']}", file=sys.stderr)
    print(f"  Reclassified rows:     {result['reclassified_rows']}", file=sys.stderr)
    for cls, count in sorted(result["by_target_class"].items()):
        print(f"    -> {cls}: {count}", file=sys.stderr)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    journal_path = args.journal or (
        _REPO_ROOT
        / "scratchpad"
        / (
            f"backfill_write_class_"
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
                "scanned_groups": result["scanned_groups"],
                "unchanged_groups": result["unchanged_groups"],
                "reclassified_groups": result["reclassified_groups"],
                "reclassified_rows": result["reclassified_rows"],
                "by_target_class": result["by_target_class"],
                "journal": result["journal"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nJournal artifact written to {journal_path}", file=sys.stderr)

    if not args.apply and result["reclassified_groups"] > 0:
        print(
            f"\nThis was a dry-run. Re-run with --apply to reclassify "
            f"{result['reclassified_rows']} rows across "
            f"{result['reclassified_groups']} source groups.",
            file=sys.stderr,
        )

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
