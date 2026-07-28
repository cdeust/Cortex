#!/usr/bin/env python3
"""Near-duplicate calibration + treatment CLI (I6-D2, INC6.4 campaign).

Three subcommands:

``sample``
    Scan candidate pairs (cosine similarity >= 0.75, approximated via
    per-row HNSW top-K — see ``pg_store_near_dup.py``), stratify around
    the write-path's 0.85 hypothesis, deterministically sub-sample ~100
    pairs, fetch contents, write a to-label artifact. Read-only.

``calibrate``
    Given a labels file (produced by hand/LLM judgment against the
    ``sample`` artifact — see ``docs/campaigns/i6d2_*_labels.json``),
    compute precision per threshold and select S. Writes a calibration
    report artifact. Read-only against the DB (uses only the labels file).

``apply``
    Given a calibrated threshold S, auto-supersede components >= S
    (reusing the I6-D1 supersede-to-existing mechanism) and write the
    review queue for [0.75, S). Dry-run by default; ``--apply`` writes.

Usage
-----

    uv run python scripts/near_dup_calibrate.py sample
    uv run python scripts/near_dup_calibrate.py calibrate \
        --labels docs/campaigns/i6d2_labels.json
    uv run python scripts/near_dup_calibrate.py apply --threshold 0.90
    uv run python scripts/near_dup_calibrate.py apply --threshold 0.90 --apply
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


async def _get_store():
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import get_shared_store

    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


async def _cmd_sample(args: argparse.Namespace) -> int:
    from mcp_server.handlers.consolidation.near_dup_calibration_pass import (
        run_near_dup_sample,
    )

    store = await _get_store()
    result = await run_near_dup_sample(
        store,
        top_k=args.top_k,
        min_similarity=args.min_similarity,
        per_stratum=args.per_stratum,
    )

    print("Near-dup candidate scan (I6-D2)", file=sys.stderr)
    print("================================", file=sys.stderr)
    print(f"  Status:            {result['status']}", file=sys.stderr)
    print(f"  Candidate total:   {result['candidate_total']}", file=sys.stderr)
    for label, count in sorted(result["histogram"].items()):
        print(f"    stratum {label}: {count}", file=sys.stderr)
    print(f"  Sample size:       {len(result['sample'])}", file=sys.stderr)

    timestamp = _timestamp()
    out_path = args.out or (
        _REPO_ROOT / "docs" / "campaigns" / f"i6d2_sample_to_label_{timestamp}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "timestamp_utc": timestamp,
                "status": result["status"],
                "min_similarity": args.min_similarity,
                "top_k": args.top_k,
                "candidate_total": result["candidate_total"],
                "histogram": result["histogram"],
                "sample": result["sample"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSample artifact written to {out_path}", file=sys.stderr)
    return 0 if result["status"] == "ok" else 1


def _cmd_calibrate(args: argparse.Namespace) -> int:
    from mcp_server.core.near_dup_calibration import (
        LabeledPair,
        precision_by_threshold,
        select_threshold,
    )

    labels_data = json.loads(args.labels.read_text(encoding="utf-8"))
    labeled = [
        LabeledPair(
            id_a=entry["id_a"],
            id_b=entry["id_b"],
            similarity=entry["similarity"],
            verdict=entry["verdict"],
            justification=entry["justification"],
        )
        for entry in labels_data["labels"]
    ]
    stats = precision_by_threshold(labeled)
    threshold = select_threshold(stats)

    print("Near-dup calibration (I6-D2)", file=sys.stderr)
    print("=============================", file=sys.stderr)
    print(f"  Labeled pairs:     {len(labeled)}", file=sys.stderr)
    for s in stats:
        print(
            f"    S={s.threshold:.2f}: n={s.n_labeled:3d}  "
            f"dup={s.n_duplicate:3d}  precision={s.precision:.3f}",
            file=sys.stderr,
        )
    selected = (
        threshold if threshold is not None else "NONE — no band reached 100% precision"
    )
    print(
        f"  Selected threshold S: {selected}",
        file=sys.stderr,
    )

    timestamp = _timestamp()
    out_path = args.out or (
        _REPO_ROOT / "docs" / "campaigns" / f"i6d2_calibration_report_{timestamp}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "timestamp_utc": timestamp,
                "labels_source": str(args.labels),
                "n_labeled": len(labeled),
                "precision_by_threshold": [
                    {
                        "threshold": s.threshold,
                        "n_labeled": s.n_labeled,
                        "n_duplicate": s.n_duplicate,
                        "precision": s.precision,
                    }
                    for s in stats
                ],
                "selected_threshold": threshold,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nCalibration report written to {out_path}", file=sys.stderr)
    return 0


async def _cmd_apply(args: argparse.Namespace) -> int:
    from mcp_server.handlers.consolidation.near_dup_calibration_pass import (
        run_near_dup_apply_pass,
    )

    store = await _get_store()
    result = await run_near_dup_apply_pass(
        store,
        threshold=args.threshold,
        apply=args.apply,
        top_k=args.top_k,
        min_similarity=args.min_similarity,
    )

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] Near-dup treatment pass (I6-D2), threshold={args.threshold}",
        file=sys.stderr,
    )
    print("=========================================================", file=sys.stderr)
    print(f"  Status:              {result['status']}", file=sys.stderr)
    print(f"  Candidate total:     {result['candidate_total']}", file=sys.stderr)
    print(f"  Components >= S:     {result['components']}", file=sys.stderr)
    print(f"  Superseded edges:    {result['superseded_total']}", file=sys.stderr)
    print(f"  Skipped (race):      {result['skipped_race']}", file=sys.stderr)
    print(f"  Skipped (vanished):  {result['skipped_vanished']}", file=sys.stderr)
    print(f"  Review queue size:   {len(result['review_queue'])}", file=sys.stderr)

    timestamp = _timestamp()
    journal_path = args.journal or (
        _REPO_ROOT
        / "docs"
        / "campaigns"
        / f"i6d2_near_dup_{'apply' if args.apply else 'dry-run'}_{timestamp}.json"
    )
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text(
        json.dumps(
            {
                "mode": mode,
                "timestamp_utc": timestamp,
                "threshold": args.threshold,
                "min_similarity": args.min_similarity,
                "status": result["status"],
                "candidate_total": result["candidate_total"],
                "components": result["components"],
                "superseded_total": result["superseded_total"],
                "skipped_race": result["skipped_race"],
                "skipped_vanished": result["skipped_vanished"],
                "journal": result["journal"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nSupersession journal written to {journal_path}", file=sys.stderr)

    review_path = args.review_out or (
        _REPO_ROOT / "docs" / "campaigns" / f"i6d2_review_queue_{timestamp}.json"
    )
    review_path.write_text(
        json.dumps(
            {
                "timestamp_utc": timestamp,
                "band": f"[{args.min_similarity}, {args.threshold})",
                "note": "Below the measured-100%-precision threshold — no "
                "auto-supersession. Each pair requires a session LLM/user "
                "decision (I6-D2 Q2 arbitration).",
                "pairs": result["review_queue"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Review queue written to {review_path}", file=sys.stderr)

    return 0 if result["status"] == "ok" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sample = sub.add_parser("sample", help="Scan + stratify + sample for labeling")
    p_sample.add_argument("--top-k", type=int, default=30)
    p_sample.add_argument("--min-similarity", type=float, default=0.75)
    p_sample.add_argument("--per-stratum", type=int, default=20)
    p_sample.add_argument("--out", type=Path, default=None)

    p_calibrate = sub.add_parser("calibrate", help="Compute precision, select S")
    p_calibrate.add_argument("--labels", type=Path, required=True)
    p_calibrate.add_argument("--out", type=Path, default=None)

    p_apply = sub.add_parser("apply", help="Auto-supersede >= S, review-queue below")
    p_apply.add_argument("--threshold", type=float, required=True)
    p_apply.add_argument("--min-similarity", type=float, default=0.75)
    p_apply.add_argument("--top-k", type=int, default=30)
    p_apply.add_argument("--apply", action="store_true")
    p_apply.add_argument("--journal", type=Path, default=None)
    p_apply.add_argument("--review-out", type=Path, default=None)

    args = parser.parse_args()

    if args.command == "sample":
        return asyncio.run(_cmd_sample(args))
    if args.command == "calibrate":
        return _cmd_calibrate(args)
    if args.command == "apply":
        return asyncio.run(_cmd_apply(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
