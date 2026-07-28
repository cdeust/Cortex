#!/usr/bin/env python3
"""Raise ``heat_base`` for active deliberate memories below the measured
retrieval cliff — I6-D5, INC6.6.

Runs ``handlers.consolidation.memory_reheat_pass`` against the shared
store and writes a campaign journal artifact (id, heat_base before/after,
effective_heat before, outcome per row — the same journalisation shape as
``memory_dedup_exact.py``, I6-D1).

Usage
-----

Dry-run (default) — scan, decide, and report, write nothing::

    uv run python scripts/memory_reheat.py

Apply the change to the DB::

    uv run python scripts/memory_reheat.py --apply

The pass is idempotent: re-running after ``--apply`` finds every
recalibrated row now at or above the target (``effective_heat >= 0.25``),
so it is excluded from the next scan's ``WHERE effective_heat < target``
filter — zero rows reheated on immediate re-run (confirmed by the
campaign's idempotence test).
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
from mcp_server.core.memory_reheat import DEFAULT_REHEAT_TARGET  # noqa: E402
from mcp_server.handlers.consolidation.memory_reheat_pass import run_memory_reheat_pass  # noqa: E402
from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: E402
from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: E402


async def _run(apply: bool, target: float, limit: int) -> dict:

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return await run_memory_reheat_pass(
        store, apply=apply, target=target or DEFAULT_REHEAT_TARGET, limit=limit
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the recalibrated heat_base values to the DB. Default is dry-run.",
    )
    parser.add_argument(
        "--target",
        type=float,
        default=0.0,
        help="Override the effective_heat target (default: the measured "
        "cliff upper bound, 0.25 — see core.memory_reheat.DEFAULT_REHEAT_TARGET).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Max candidate rows to scan in this run (default 5000, "
        "comfortably covers the known ~550-750-row deliberate stock).",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=None,
        help="Path to write the campaign journal JSON artifact (default: "
        "docs/campaigns/i6d5_memory_reheat_<dry-run|apply>_<UTC-timestamp>.json).",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] scanning active deliberate memories below target "
        f"(target={args.target or 'default(0.25)'}, limit={args.limit})",
        file=sys.stderr,
    )

    result = asyncio.run(_run(args.apply, args.target, args.limit))

    print("", file=sys.stderr)
    print("Deliberate heat recalibration summary (I6-D5)", file=sys.stderr)
    print("===============================================", file=sys.stderr)
    print(f"  Status:                {result['status']}", file=sys.stderr)
    print(f"  Target eh:             {result['target']}", file=sys.stderr)
    print(f"  Scanned rows:          {result['scanned_rows']}", file=sys.stderr)
    print(f"  Reheated:              {result['reheated']}", file=sys.stderr)
    print(f"  Unreachable (at max):  {result['unreachable']}", file=sys.stderr)
    print(
        f"  Already above target:  {result['already_above_target']}",
        file=sys.stderr,
    )
    print(f"  Skipped (race/CAS):    {result['skipped_race']}", file=sys.stderr)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    journal_path = args.journal or (
        _REPO_ROOT
        / "docs"
        / "campaigns"
        / f"i6d5_memory_reheat_{'apply' if args.apply else 'dry-run'}_{timestamp}.json"
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps(
            {
                "mode": mode,
                "timestamp_utc": timestamp,
                "target": result["target"],
                "limit": args.limit,
                "status": result["status"],
                "scanned_rows": result["scanned_rows"],
                "reheated": result["reheated"],
                "unreachable": result["unreachable"],
                "already_above_target": result["already_above_target"],
                "skipped_race": result["skipped_race"],
                "journal": result["journal"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nJournal artifact written to {journal_path}", file=sys.stderr)

    if not args.apply and result["reheated"] > 0:
        print(
            f"\nThis was a dry-run. Re-run with --apply to raise heat_base "
            f"on {result['reheated']} deliberate memories.",
            file=sys.stderr,
        )

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
