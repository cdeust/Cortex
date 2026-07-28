#!/usr/bin/env python3
"""Backfill the domain of memories stuck with ``domain = ''`` — I6-D3.

Runs ``handlers.consolidation.memory_domain_backfill_pass`` against the
shared store and writes a campaign journal artifact (id, evidence
source, derived domain per row — I6-D3's "journalisation" requirement).

Usage
-----

Dry-run (default) — derive and report, write nothing::

    uv run python scripts/memory_domain_backfill.py

Apply the change to the DB::

    uv run python scripts/memory_domain_backfill.py --apply

The pass is idempotent: re-running after ``--apply`` finds zero rows
left to backfill (``list_domainless_memories`` only returns rows still
empty), and never overwrites a domain some other writer already set
(``pg_store_memory_domain.update_memory_domain``'s guarded UPDATE).
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
from mcp_server.handlers.consolidation.memory_domain_backfill_pass import (  # noqa: E402
    run_memory_domain_backfill_pass,
)
from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: E402
from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: E402


async def _run(apply: bool, limit: int, include_orphans: bool) -> dict:

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return await run_memory_domain_backfill_pass(
        store, apply=apply, limit=limit, include_orphans=include_orphans
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the derived domains/orphan tags to the DB. Default is dry-run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Max rows to scan in this run "
        "(default 5000, covers the known ~1355 stock).",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=None,
        help="Path to write the campaign journal JSON artifact (default: "
        "scratchpad/memory_domain_backfill_<dry-run|apply>_<UTC-timestamp>.json).",
    )
    parser.add_argument(
        "--include-orphans",
        action="store_true",
        help="Also rescan rows already tagged 'domain-orphan'. Use only "
        "after a change to the resolution logic itself (e.g. a "
        "domain_mapping.py fix) that could newly resolve rows the old "
        "logic could not (INC6.2). A row that resolves on rescan has its "
        "'domain-orphan' tag removed automatically. Default: off — "
        "orphans are otherwise a terminal state, excluded from the scan.",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] scanning memories with empty domain (limit={args.limit}, "
        f"include_orphans={args.include_orphans})",
        file=sys.stderr,
    )

    result = asyncio.run(_run(args.apply, args.limit, args.include_orphans))

    print("", file=sys.stderr)
    print("Memory domain backfill summary (I6-D3)", file=sys.stderr)
    print("=======================================", file=sys.stderr)
    print(f"  Status:                 {result['status']}", file=sys.stderr)
    print(f"  Scanned:                {result['scanned']}", file=sys.stderr)
    print(
        f"  Filled (directory_context): "
        f"{result['by_evidence'].get('directory_context', 0)}",
        file=sys.stderr,
    )
    print(
        f"  Filled (project_tag):       {result['by_evidence'].get('project_tag', 0)}",
        file=sys.stderr,
    )
    print(f"  Filled total:           {result['filled']}", file=sys.stderr)
    print(f"  Orphaned (tagged):      {result['orphaned']}", file=sys.stderr)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    journal_path = args.journal or (
        _REPO_ROOT
        / "scratchpad"
        / (
            f"memory_domain_backfill_"
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
                "scanned": result["scanned"],
                "filled": result["filled"],
                "orphaned": result["orphaned"],
                "by_evidence": result["by_evidence"],
                "journal": result["journal"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nJournal artifact written to {journal_path}", file=sys.stderr)

    if not args.apply and result["scanned"] > 0:
        print(
            f"\nThis was a dry-run. Re-run with --apply to write "
            f"{result['filled']} domains + {result['orphaned']} orphan tags.",
            file=sys.stderr,
        )

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
