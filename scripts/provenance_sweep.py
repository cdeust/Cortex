#!/usr/bin/env python3
"""Full-corpus provenance sweep — I6-D6 grader run at scale (M-D5, 7.5).

The grader itself (``handlers/validate_memory.py``) already exists and is
the sole writer of ``memories.source_attribution``'s grade vocabulary
(verified/verifiable/unverifiable) — this script adds NOTHING new to the
grading logic. It is a thin, paginated driver: the corpus-wide pass the
I6-D6 design specified but that had never been run past a 100-row sample
(inc6.5) or the full store (§0.4 of the design doc: 72/10 079 graded).

Runs ``handlers.validate_memory.handler`` repeatedly, following its own
``after_id`` cursor (1000 rows/call) until ``next_after_id`` is ``None``,
and writes a campaign journal artifact: before/after grade distribution,
per-page counts, and a bounded sample of per-memory reports.

Usage
-----

Dry-run (default) — grade every memory and report, write nothing::

    uv run python scripts/provenance_sweep.py

Apply the change to the DB (NOT run by this increment's author — the
orchestrator decides, per the 7.5 task mandate)::

    uv run python scripts/provenance_sweep.py --apply

The pass is idempotent by construction (validate_memory.py's own
contract, i6d6): re-running after ``--apply`` re-computes the same grade
for a memory whose references haven't changed and writes the identical
value — zero DB deltas on a stable corpus, confirmed per-memory in
``tests_py/handlers/test_validate_memory.py::TestProvenanceIdempotence``.

Network bound: ``--url-check-limit`` caps DISTINCT URLs HEAD-checked PER
PAGE (default 0 for this driver — see the module docstring's rationale;
override for a network-connected run). URLs beyond the limit are graded
"not sampled this pass" (ceiling verifiable, never penalized as dead).
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
from mcp_server.handlers import validate_memory  # noqa: E402
from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: E402
from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: E402

_GRADES = ("verified", "verifiable", "unverifiable")

# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MAX_SAMPLE_REPORTS = 200


async def _fetch_current_distribution(store) -> dict[str, int]:
    """Raw count of every row's CURRENT source_attribution value — the
    same population validate_memory's own cursor will visit
    (``get_all_memories_for_validation`` filters only on ``id`` and
    ``is_stale`` when ``include_stale=True`` is passed, which this
    handler always does — see that method's docstring)."""
    rows = store._execute(
        "SELECT COALESCE(source_attribution, 'unknown') AS grade, count(*) AS n "
        "FROM memories GROUP BY 1"
    ).fetchall()
    return {
        (r["grade"] if isinstance(r, dict) else r[0]): (
            r["n"] if isinstance(r, dict) else r[1]
        )
        for r in rows
    }


async def _run(
    apply: bool, url_check_limit: int, page_limit: int, max_pages: int
) -> dict:

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)

    before = await _fetch_current_distribution(store)

    after_id = 0
    pages = 0
    validated_total = 0
    stale_found_total = 0
    stale_updated_total = 0
    destaled_total = 0
    graded_total = 0
    projected_grades = dict.fromkeys(_GRADES, 0)
    per_page: list[dict] = []
    sample_reports: list[dict] = []

    while pages < max_pages:
        result = await validate_memory.handler(
            {
                "after_id": after_id,
                "url_check_limit": url_check_limit,
                "dry_run": not apply,
            }
        )
        pages += 1
        validated_total += result["validated"]
        stale_found_total += result["stale_found"]
        stale_updated_total += result["stale_updated"]
        destaled_total += result["destaled"]
        graded_total += result["graded"]
        per_page.append(
            {
                "page": pages,
                "after_id_start": after_id,
                "validated": result["validated"],
                "next_after_id": result["next_after_id"],
            }
        )
        for r in result["reports"]:
            grade = r["provenance_grade"]
            projected_grades[grade] += 1
            # Reclassification transitions are read from the CURRENT (not
            # yet mutated on dry-run) DB row via the report's memory_id —
            # cheap because reports already carry the field we need.
            if len(sample_reports) < _MAX_SAMPLE_REPORTS:
                sample_reports.append(
                    {
                        "memory_id": r["memory_id"],
                        "grade": grade,
                        "ref_counts": r["ref_counts"],
                        "reason": r["provenance_reason"],
                    }
                )

        if result["next_after_id"] is None:
            break
        after_id = result["next_after_id"]

    return {
        "before_distribution": before,
        "projected_grade_distribution": projected_grades,
        "pages": pages,
        "validated_total": validated_total,
        "stale_found_total": stale_found_total,
        "stale_updated_total": stale_updated_total,
        "destaled_total": destaled_total,
        "graded_total": graded_total,
        "per_page": per_page,
        "sample_reports": sample_reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the computed grades to source_attribution. Default is "
        "dry-run. NOT invoked by the 7.5 increment author per task "
        "mandate — the orchestrator decides.",
    )
    parser.add_argument(
        "--url-check-limit",
        type=int,
        default=0,
        help="Distinct URLs HEAD-checked per page (default 0 — this "
        "driver's default keeps the corpus-wide sweep network-free and "
        "reproducible in a sandboxed environment; override for a "
        "network-connected production run).",
    )
    parser.add_argument(
        "--page-limit",
        type=int,
        default=1000,
        help="Rows per validate_memory call (handler's own cap is 1000).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Safety bound on pagination iterations (default 50 * 1000 "
        "rows = 50k, comfortably covers the measured ~11k-row corpus).",
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=None,
        help="Path to write the campaign journal JSON artifact (default: "
        "docs/campaigns/i7d5_provenance_sweep_<dry-run|apply>_<UTC-timestamp>.json).",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] full-corpus provenance sweep (url_check_limit="
        f"{args.url_check_limit}, page_limit={args.page_limit}, "
        f"max_pages={args.max_pages})",
        file=sys.stderr,
    )

    result = asyncio.run(
        _run(args.apply, args.url_check_limit, args.page_limit, args.max_pages)
    )

    print("", file=sys.stderr)
    print("Provenance sweep summary (M-D5, 7.5)", file=sys.stderr)
    print("=====================================", file=sys.stderr)
    print(f"  Status:               {mode}", file=sys.stderr)
    print(f"  Pages:                {result['pages']}", file=sys.stderr)
    print(f"  Validated (total):    {result['validated_total']}", file=sys.stderr)
    print(f"  Stale found (fresh):  {result['stale_found_total']}", file=sys.stderr)
    print(f"  Stale newly marked:   {result['stale_updated_total']}", file=sys.stderr)
    print(f"  De-staled:            {result['destaled_total']}", file=sys.stderr)
    print(f"  Graded (written):     {result['graded_total']}", file=sys.stderr)
    print(f"  Before distribution:  {result['before_distribution']}", file=sys.stderr)
    print(
        f"  Projected/new grades: {result['projected_grade_distribution']}",
        file=sys.stderr,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    journal_path = args.journal or (
        _REPO_ROOT
        / "docs"
        / "campaigns"
        / (
            f"i7d5_provenance_sweep_"
            f"{'apply' if args.apply else 'dry-run'}_{timestamp}.json"
        )
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps(
            {
                "mode": mode,
                "timestamp_utc": timestamp,
                "url_check_limit": args.url_check_limit,
                "page_limit": args.page_limit,
                "max_pages": args.max_pages,
                **result,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nJournal artifact written to {journal_path}", file=sys.stderr)

    if not args.apply:
        print(
            "\nThis was a dry-run. Nothing was written to source_attribution. "
            "Re-run with --apply (orchestrator decision, per task mandate) to "
            "persist the projected grades.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
