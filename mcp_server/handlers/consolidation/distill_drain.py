"""Distillation leg of the scheduled groomer (G-3) — drains
``curate_distill`` jobs via ``claude -p``, reusing headless_authoring's
budget/concurrency/sandbox machinery.

Unlike the wiki leg (``cycle_orchestration.run_headless_authoring_cycle``),
where the ``claude -p`` response is TEXT that the *parent* process writes
to disk via ``wiki_write.write_governed_page``, here the LLM is expected
to call ``remember`` itself over MCP inside the child process:
``core.distillation_reporting.build_distill_prompt`` (reused verbatim,
INC7.8/M-D8 — not reimplemented here) already encodes the exact required
``remember(...)`` call shape (tags include the dossier's idempotence
marker + one ``derived-src:<id>`` per source, ``write_class='deliberate'``)
in the prompt text itself. This module never calls ``remember`` or
``wiki_write`` — the child's own MCP tool call, if it makes one, is the
only write this leg can produce; this module only counts outcomes.

Precondition for any write at all: ``CORTEX_HEADLESS_AGENTS=1`` (the
default). Solo mode (``CORTEX_HEADLESS_AGENTS=0``) passes ``--safe-mode``
to the child, which disables MCP servers entirely (``claude_cli.py``'s own
documented contract) — a distill job's ``remember`` call could not
possibly reach the DB under solo mode. This module detects that up front
and reports every job as ``skipped-solo-mode`` rather than spending a
``claude -p`` call that is structurally unable to write anything.

INVARIANT (grooming-continu design doc, contractual, never relaxed): this
module never imports or calls ``lesson_promotion.handler``. Promotion
stays exclusively a human-in-session decision — see
``mcp_server/handlers/lesson_promotion.py``'s own docstring ("No
auto-promotion, ever: a rule reshapes every future recall ... so the
decision stays with the LLM/user reading the job"). The reminder appended
to every prompt below is advisory defence-in-depth only (matches
``claude_cli.py``'s own "Advisory (NOT counted as enforcing)" language for
its untrusted-content delimiter) — MCP tool calls are not gated by
``--disallowedTools``, so this is not a hard sandbox boundary.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import headless_authoring as _root

# Advisory-only reminder appended to every distill prompt sent to the
# child. Not an enforcing control (MCP tool calls are not gated by
# --disallowedTools — see module docstring); defence-in-depth alongside
# the structural invariant that this module itself never calls
# lesson_promotion.handler.
_NO_PROMOTION_REMINDER = (
    "\n\n---\nReminder: this session's only sanctioned MCP write is the "
    "single `remember` call the prompt above specifies. Do not call "
    "`lesson_promotion`, `add_rule`, or `create_trigger` in this session."
)


@dataclass
class DistillDrainResult:
    """One distillation job's outcome."""

    marker: str
    dossier_kind: str
    status: str  # "attempted" | "skipped-solo-mode" | "skipped-budget" | "failed"
    duration_ms: int
    cost_usd: float
    detail: str = ""


@dataclass
class DistillCycleSummary:
    """Per-invocation roll-up, mirrors headless_authoring.CycleSummary's
    field naming for a consistent journal shape across both legs."""

    jobs_offered: int
    attempted: int
    skipped_solo_mode: int
    skipped_budget: int
    failed: int
    usd_spent: float
    wall_clock_ms: int
    results: list[DistillDrainResult] = field(default_factory=list)


async def run_distill_drain_cycle(
    jobs: list[dict[str, Any]],
    *,
    invoke: Callable[..., Any] | None = None,
) -> DistillCycleSummary:
    """Drain up to ``len(jobs)`` ``curate_distill`` jobs via ``claude -p``.

    Precondition: ``jobs`` are ``curate_distill.handler()["jobs"]`` entries
    — each already carries a ready-built ``prompt`` (see
    ``core.distillation_reporting.build_distill_prompt``). ``invoke`` is
    an async callable matching ``headless_authoring._claude_invoke``'s
    signature (DI seam for tests); defaults to the real implementation.
    Postcondition: every job in ``jobs`` produces exactly one
    ``DistillDrainResult``. This function itself never creates, updates,
    or tags a memory row — any ``remember`` call happens inside the
    ``claude -p`` child, entirely outside this process's control; this
    function only counts outcomes reported by the subprocess call.
    Invariant: no more than ``CORTEX_HEADLESS_CONCURRENCY`` in-flight
    ``claude -p`` subprocesses at any point (same semaphore discipline as
    ``cycle_orchestration.run_headless_authoring_cycle``).
    """
    cycle_start = time.monotonic()
    invoke_fn = invoke if invoke is not None else _root._claude_invoke

    if _root.CORTEX_HEADLESS_AGENTS == 0:
        results = [
            DistillDrainResult(
                marker=job.get("marker", ""),
                dossier_kind=job.get("dossier_kind", ""),
                status="skipped-solo-mode",
                duration_ms=0,
                cost_usd=0.0,
                detail="CORTEX_HEADLESS_AGENTS=0 (--safe-mode) disables "
                "MCP servers in the child; remember() cannot reach the DB",
            )
            for job in jobs
        ]
        return DistillCycleSummary(
            jobs_offered=len(jobs),
            attempted=0,
            skipped_solo_mode=len(jobs),
            skipped_budget=0,
            failed=0,
            usd_spent=0.0,
            wall_clock_ms=int((time.monotonic() - cycle_start) * 1000),
            results=results,
        )

    budget = _root.CycleBudget(
        deadline=time.monotonic() + _root.CORTEX_HEADLESS_BUDGET_SEC,
        usd_cap=_root.CORTEX_HEADLESS_USD_BUDGET,
    )
    sem = asyncio.Semaphore(_root.CORTEX_HEADLESS_CONCURRENCY)

    async def _drain_one(job: dict[str, Any]) -> DistillDrainResult:
        async with sem:
            if _root.cycle_budget_exhausted(budget):
                return DistillDrainResult(
                    marker=job.get("marker", ""),
                    dossier_kind=job.get("dossier_kind", ""),
                    status="skipped-budget",
                    duration_ms=0,
                    cost_usd=0.0,
                    detail="budget exhausted",
                )
            t0 = time.monotonic()
            prompt = str(job.get("prompt", "")) + _NO_PROMOTION_REMINDER
            eff_timeout = max(
                1.0,
                min(
                    float(_root.CLAUDE_CALL_TIMEOUT_SEC),
                    _root.cycle_budget_time_left(budget),
                ),
            )
            ir = await invoke_fn(prompt, timeout=eff_timeout)
            _root.cycle_budget_charge(budget, ir.cost_usd)
            ms = int((time.monotonic() - t0) * 1000)
            status = "attempted" if ir.text else "failed"
            return DistillDrainResult(
                marker=job.get("marker", ""),
                dossier_kind=job.get("dossier_kind", ""),
                status=status,
                duration_ms=ms,
                cost_usd=ir.cost_usd,
                detail="" if ir.text else "claude returned empty/failed",
            )

    coros = [_drain_one(job) for job in jobs]
    results = list(await asyncio.gather(*coros)) if coros else []

    attempted = sum(1 for r in results if r.status == "attempted")
    failed = sum(1 for r in results if r.status == "failed")
    skipped_budget = sum(1 for r in results if r.status == "skipped-budget")
    wall_ms = int((time.monotonic() - cycle_start) * 1000)

    return DistillCycleSummary(
        jobs_offered=len(jobs),
        attempted=attempted,
        skipped_solo_mode=0,
        skipped_budget=skipped_budget,
        failed=failed,
        usd_spent=budget.usd_spent,
        wall_clock_ms=wall_ms,
        results=results,
    )
