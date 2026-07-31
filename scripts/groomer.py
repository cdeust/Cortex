#!/usr/bin/env python3
"""Scheduled groomer — the judgment-level grooming session (G-3, "grooming
continu" program).

Design of record: scratchpad ``grooming-continu-design.md`` §4 Incrément 3
("session planifiée headless, dry-run d'abord"). Depends on G-1 (headless
write-path governance — every write this script's children can make goes
through ``wiki_write.write_governed_page`` or an explicit ``remember`` MCP
call, never a raw disk write) and G-4 (``get_grooming_health`` — the
backlog/staleness signal this script reads before deciding to run).

What this script does
----------------------
1. Calls ``get_grooming_health`` to read backlog + staleness for the
   ``wiki`` and ``distillation`` legs (``core.grooming_health.legs_due``
   decides which legs are actually due — stale AND non-empty backlog).
2. **Wiki leg**: drains curation-gap/anchor pages via the EXISTING
   ``headless_authoring.run_headless_authoring_cycle`` — the ``claude -p``
   child returns markdown TEXT that this process writes through the
   governed path (G-1). Bounded by ``CORTEX_HEADLESS_MAX_FILE_DRAINS`` /
   ``CORTEX_HEADLESS_MAX_ANCHOR_DRAINS`` (existing env-tunable policy
   caps, default 8+8 — not new constants).
3. **Distillation leg**: fetches up to ``--distill-limit`` jobs from
   ``curate_distill`` (default 5 — reusing that handler's OWN existing
   default, ``curate_distill.py``'s ``limit = 5 if limit is None``, not an
   invented number) and drains them via
   ``handlers.consolidation.distill_drain.run_distill_drain_cycle`` — here
   the ``claude -p`` child calls ``remember`` itself over MCP, using the
   prompt ``curate_distill`` already built (``build_distill_prompt``,
   INC7.8) verbatim plus an advisory no-promotion reminder.
4. **Promotion**: NEVER executed. ``lesson_promotion.handler`` is never
   imported or called anywhere in this script or in the modules it calls
   (grep-verified in ``test_groomer_never_calls_lesson_promotion``). Its
   backlog count (already surfaced by ``get_grooming_health``, itself a
   read-only ``COUNT(*)``, not the promotion handler) is only ever
   reported in the journal for a human to act on.

KNOWN SCOPE GAP (documented honestly, not silently papered over): the
``wiki`` leg's due/not-due DECISION uses ``get_grooming_health``'s
``wiki`` staleness, which is itself sourced from ``curate_wiki``'s
CLUSTER/coverage/reauthor backlog (``total_clusters_eligible``) — but the
leg this script actually RUNS when wiki is due is
``headless_authoring.run_headless_authoring_cycle``, which drains a
DIFFERENT queue entirely: pages carrying ``curation_gaps`` frontmatter and
missing anchor pages (design doc §1.4 — headless_authoring's scope was
always narrower than ``curate_wiki``'s cluster jobs, and this script does
not change that). A "wiki is stale" signal therefore does not guarantee
``run_headless_authoring_cycle`` finds anything to drain, and a fresh
``wiki.pages.tended`` timestamp does not mean the cluster backlog shrank.
Extending ``headless_authoring`` to also drain ``curate_wiki``'s
cluster/coverage/reauthor jobs (the design doc's original, larger
Incrément-3 sketch) is explicitly OUT OF SCOPE for this increment — it
reuses the existing G-1-governed mechanism as-is, per this increment's own
brief. Track this gap before assuming the ``wiki`` staleness alarm and the
wiki leg's actual output are tightly coupled.

Combined worst-case cost per apply run, both legs at full budget: up to
16 wiki ``claude -p`` calls (8 file-doc + 8 anchor, existing caps) + 5
distillation calls = 21 calls, each independently capped at
``CORTEX_HEADLESS_USD_BUDGET`` (default $5) and
``CORTEX_HEADLESS_BUDGET_SEC`` (default 300s) PER LEG — so up to $10 / up
to ~10 minutes wall-clock per scheduled run in the worst case, consistent
with the design doc's own §3(a) estimate ("15-25 appels claude -p,
≈5-10 USD/run"). Tune via the existing ``CORTEX_HEADLESS_*`` env vars;
this script introduces no new budget knobs.

Dry-run is the default: with no ``--apply`` flag, this script only reads
(``get_grooming_health`` + a bounded ``curate_distill`` preview call, both
READ_ONLY handlers) and reports what it WOULD do. ``--apply`` additionally
requires ``CORTEX_HEADLESS_AUTHORING=1`` set in the environment (matching
``wiki_maintenance._headless_authoring_enabled``'s existing opt-in gate) —
refuses to write otherwise, even with ``--apply`` passed.

A campaign journal (JSON + Markdown, same shape as
``scripts/wiki_citation_seed.py``'s pattern) is written to
``docs/campaigns/`` on every run, dry-run or apply.

See ``docs/groomer-scheduling.md`` for the launchd installation procedure,
cadence justification, and the active-session guard rail.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from mcp_server.core.grooming_health import legs_due  # noqa: E402
from mcp_server.handlers.get_grooming_health import handler as health_handler  # noqa: E402
from mcp_server.handlers.curate_distill import handler as distill_handler  # noqa: E402
from mcp_server.infrastructure.session_registry import has_active_session_window  # noqa: E402
from mcp_server.handlers.consolidation.headless_authoring import (  # noqa: E402
    run_headless_authoring_cycle,
    CORTEX_HEADLESS_MAX_ANCHOR_DRAINS,
    CORTEX_HEADLESS_MAX_FILE_DRAINS,
)
from mcp_server.handlers.consolidation.distill_drain import run_distill_drain_cycle  # noqa: E402


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses to plain dicts for json.dumps.

    Precondition: none. Postcondition: dataclasses become dicts (their
    own fields recursed), lists/dicts recursed, everything else passed
    through unchanged.
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    return obj


async def _run(
    *,
    apply: bool,
    wiki_max_drains: int,
    wiki_max_anchor_drains: int,
    distill_limit: int,
    force: bool,
) -> dict[str, Any]:
    """Read grooming health, decide which legs are due, run them (or
    preview them in dry-run), and return the full result for journaling.

    Precondition: none.
    Postcondition: when ``apply=False``, no memory row, wiki page, or
    citation is created/updated anywhere this call can reach — only
    READ_ONLY handlers (``get_grooming_health``, ``curate_distill`` with
    a bounded preview limit) are invoked. When ``apply=True``, at most
    the wiki and distillation legs run, gated by ``legs_due`` and the
    active-session guard; ``lesson_promotion.handler`` is NEVER called by
    this function, in either mode.
    """

    health = await health_handler({})
    due = legs_due(health["kinds"], force=force)

    result: dict[str, Any] = {
        "health": health,
        "due": due,
        "mode": "apply" if apply else "dry-run",
        "active_session_guard": None,
        "wiki": None,
        "distill": None,
        "promotion_backlog_reported_only": health["kinds"].get("promotion"),
    }

    if not apply:
        wiki_preview: dict[str, Any] = {"would_run": due["wiki"]}
        if due["wiki"]:
            wiki_preview["max_file_drains"] = wiki_max_drains
            wiki_preview["max_anchor_drains"] = wiki_max_anchor_drains
        result["wiki"] = wiki_preview

        distill_preview: dict[str, Any] = {"would_run": due["distillation"]}
        if due["distillation"]:
            preview = await distill_handler({"limit": distill_limit})
            distill_preview["jobs_offered"] = preview["returned"]
            distill_preview["total_dossiers_eligible"] = preview[
                "total_dossiers_eligible"
            ]
            distill_preview["jobs"] = [
                {
                    "marker": j.get("marker"),
                    "dossier_kind": j.get("dossier_kind"),
                    "prompt_preview": str(j.get("prompt", ""))[:200],
                }
                for j in preview["jobs"]
            ]
        result["distill"] = distill_preview
        return result

    if os.environ.get("CORTEX_HEADLESS_AUTHORING") != "1":
        raise SystemExit(  # noqa: TRY003 — one-off message, not reused (§3.3)
            "--apply requires CORTEX_HEADLESS_AUTHORING=1 explicitly set "
            "in the environment (matches wiki_maintenance's existing "
            "opt-in gate). Refusing to write without it."
        )

    if has_active_session_window():
        result["active_session_guard"] = (
            "skipped: an interactive Claude Code session window is active"
        )
        return result

    if due["wiki"]:
        wiki_summary = await run_headless_authoring_cycle(
            max_drains=wiki_max_drains, max_anchor_drains=wiki_max_anchor_drains
        )
        result["wiki"] = {"ran": True, **_to_jsonable(wiki_summary)}
    else:
        result["wiki"] = {"ran": False, "reason": "not due (fresh or empty backlog)"}

    if due["distillation"]:
        distill_jobs = await distill_handler({"limit": distill_limit})
        distill_summary = await run_distill_drain_cycle(distill_jobs["jobs"])
        result["distill"] = {"ran": True, **_to_jsonable(distill_summary)}
    else:
        result["distill"] = {
            "ran": False,
            "reason": "not due (fresh or empty backlog)",
        }

    return result


def _write_journal(result: dict[str, Any], journal_dir: Path, mode: str) -> Path:
    """Write the JSON + Markdown campaign journal artifacts.

    Precondition: ``journal_dir`` may not exist yet.
    Postcondition: two files written under ``journal_dir``, same naming
    convention as ``scripts/wiki_citation_seed.py``
    (``g3_groomer_<mode>_<UTC-timestamp>.{json,md}``); returns the JSON
    path.
    """
    journal_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"g3_groomer_{mode}_{timestamp}"
    json_path = journal_dir / f"{stem}.json"
    md_path = journal_dir / f"{stem}.md"

    json_path.write_text(
        json.dumps({"timestamp_utc": timestamp, "mode": mode, **result}, indent=2),
        encoding="utf-8",
    )

    kinds = result["health"]["kinds"]
    lines = [
        f"# Scheduled groomer run — {mode} — {timestamp}",
        "",
        "## Backlog + staleness (get_grooming_health)",
        "",
        "| Kind | Backlog | Stale | Days since last run |",
        "|---|---|---|---|",
    ]
    for kind_name, k in kinds.items():
        lines.append(
            f"| {kind_name} | {k['backlog_count']} | {k['stale']} | "
            f"{k['days_since_last_run']} |"
        )
    lines += [
        "",
        f"Threshold: {result['health']['threshold_days']} days.",
        "",
        "## Legs due this run",
        "",
        f"- wiki: {result['due']['wiki']}",
        f"- distillation: {result['due']['distillation']}",
        "- promotion: NEVER (contractual invariant — see module docstring "
        "of scripts/groomer.py and handlers/lesson_promotion.py)",
        "",
    ]
    if result.get("active_session_guard"):
        lines += ["## Guarded", "", result["active_session_guard"], ""]
    lines += [
        "## Wiki leg",
        "",
        f"```json\n{json.dumps(result['wiki'], indent=2)}\n```",
        "",
        "## Distillation leg",
        "",
        f"```json\n{json.dumps(result['distill'], indent=2)}\n```",
        "",
        "## Promotion backlog (reported only, never executed)",
        "",
        f"```json\n"
        f"{json.dumps(result['promotion_backlog_reported_only'], indent=2)}\n```",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually run due legs and let their claude -p children "
        "write (wiki via the governed path, distillation via the "
        "child's own `remember` MCP call). Requires "
        "CORTEX_HEADLESS_AUTHORING=1 in the environment. Default: "
        "dry-run (report only, write nothing).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Mark wiki + distillation legs due regardless of "
        "staleness/backlog (never affects promotion — see module "
        "docstring). For manual/debug invocation, not the cron path.",
    )
    parser.add_argument(
        "--wiki-max-drains",
        type=int,
        default=None,
        help="Max file-doc gap drains for the wiki leg (default: "
        "headless_authoring.CORTEX_HEADLESS_MAX_FILE_DRAINS, env-tunable).",
    )
    parser.add_argument(
        "--wiki-max-anchor-drains",
        type=int,
        default=None,
        help="Max anchor-page drains for the wiki leg (default: "
        "headless_authoring.CORTEX_HEADLESS_MAX_ANCHOR_DRAINS, "
        "env-tunable).",
    )
    parser.add_argument(
        "--distill-limit",
        type=int,
        default=5,
        help="Max distillation jobs to offer per run (default: 5, "
        "reusing curate_distill.handler's own existing default).",
    )
    parser.add_argument(
        "--journal-dir",
        type=Path,
        default=_REPO_ROOT / "docs" / "campaigns",
        help="Directory for the JSON+Markdown journal artifacts.",
    )
    args = parser.parse_args()

    wiki_max_drains = (
        args.wiki_max_drains
        if args.wiki_max_drains is not None
        else CORTEX_HEADLESS_MAX_FILE_DRAINS
    )
    wiki_max_anchor_drains = (
        args.wiki_max_anchor_drains
        if args.wiki_max_anchor_drains is not None
        else CORTEX_HEADLESS_MAX_ANCHOR_DRAINS
    )

    mode = "apply" if args.apply else "dry-run"
    print(f"[{mode}] scheduled groomer (G-3) starting", file=sys.stderr)

    result = asyncio.run(
        _run(
            apply=args.apply,
            wiki_max_drains=wiki_max_drains,
            wiki_max_anchor_drains=wiki_max_anchor_drains,
            distill_limit=args.distill_limit,
            force=args.force,
        )
    )

    journal_path = _write_journal(result, args.journal_dir, mode)

    print("", file=sys.stderr)
    print("Scheduled groomer summary (G-3)", file=sys.stderr)
    print("================================", file=sys.stderr)
    print(f"  Mode:                  {mode}", file=sys.stderr)
    print(f"  Wiki due:              {result['due']['wiki']}", file=sys.stderr)
    print(f"  Distillation due:      {result['due']['distillation']}", file=sys.stderr)
    print(
        f"  Promotion backlog:     "
        f"{result['promotion_backlog_reported_only'].get('backlog_count')} "
        "(reported only, never executed)",
        file=sys.stderr,
    )
    if result.get("active_session_guard"):
        print(
            f"  Guard:                 {result['active_session_guard']}",
            file=sys.stderr,
        )
    print(f"\nJournal artifact written to {journal_path}", file=sys.stderr)

    if not args.apply:
        print(
            "\nThis was a dry-run. Re-run with --apply "
            "(CORTEX_HEADLESS_AUTHORING=1 required) to execute due legs.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
