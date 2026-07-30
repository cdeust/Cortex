"""Concurrent cycle orchestration for the headless authoring worker.

The original cycle called drain functions SEQUENTIALLY on the event
loop, spawning up to ~38 ``claude -p`` subprocesses one-at-a-time.
The new design:
  1. Builds the full candidate list (no claude calls yet).
  2. Scatters all candidates concurrently via asyncio.gather, bounded
     by CORTEX_HEADLESS_CONCURRENCY (asyncio.Semaphore).
  3. Each coroutine checks CycleBudget before calling invoke;
     exhausted candidates return status="skipped" immediately.
  4. cost_usd from InvokeResult charges the budget after each call.

Split out of ``headless_authoring`` (Fowler: Move Function); the public
import surface remains ``headless_authoring``, which re-exports
``run_headless_authoring_cycle``.

Patchability contract: the throttle tests do
``monkeypatch.setattr(ha, "CORTEX_HEADLESS_CONCURRENCY", 2)`` (and
similarly for ``_collect_anchor_candidates`` / ``_scan_pages_with_gaps``)
then call ``run_headless_authoring_cycle`` — every name below MUST
resolve off the live ``headless_authoring`` module at CALL time for
those patches to be observed.

Import-cycle note (issue #237): a module-top ``from . import
headless_authoring as _root`` would deadlock a fresh interpreter (it
imports ``run_headless_authoring_cycle`` back at load time). ``_root``
is bound once, in ``run_headless_authoring_cycle``, and passed
explicitly to every helper below (Extract Function, issue #276 — the
two coroutines that used to close over it as a local now take it as a
parameter) — every ``_root.X`` access still resolves at call time.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .drain_operations import _drain_result, _elapsed_ms, drain_all_gaps_on_page
from .page_io import _scope_anchor_prompt, _write_anchor_page
from datetime import datetime, timezone
from mcp_server.infrastructure.config import WIKI_ROOT


def _build_cycle_candidates(
    wiki_root: Path, max_drains: int, max_anchor_drains: int, _root: Any
) -> tuple[list[Any], list[tuple[Path, dict[str, Any], str]], list[Any]]:
    """Phase 1: build the full candidate list (no claude calls yet).

    Returns ``(anchor_cands, file_cands, file_cands_raw)`` — the last is
    the unsliced scan result, kept for the cycle summary's pages_scanned.
    """
    anchor_cands = _root._collect_anchor_candidates(wiki_root, max_anchor_drains)
    file_cands_raw = _root._scan_pages_with_gaps(wiki_root)
    file_cands_raw.sort(
        key=lambda c: (-(len(c[1].get("curation_gaps") or [])), str(c[0]))
    )
    file_cands = file_cands_raw[:max_drains]
    return anchor_cands, file_cands, file_cands_raw


async def _invoke_anchor_call(
    cand: Any, invoke: Callable[..., Awaitable[Any]], budget: Any, _root: Any
) -> tuple[Any, int]:
    """Build the anchor prompt, invoke claude under a budget-aware timeout,
    charge the budget, and return (ir, elapsed_ms).
    """
    t0 = time.monotonic()
    prompt = _scope_anchor_prompt(
        domain=cand.domain,
        scope_name=cand.scope_name,
        scope_title=cand.scope_title,
        scope_description=cand.scope_description,
        source_root=cand.source_root,
    )
    # Effective per-call timeout = remaining budget time, capped at
    # CLAUDE_CALL_TIMEOUT_SEC and floored at 1 s.
    eff_timeout = max(
        1.0, min(float(_root.CLAUDE_CALL_TIMEOUT_SEC), budget.time_left())
    )
    ir = await invoke(
        prompt, cwd=cand.source_root, source_root=cand.source_root, timeout=eff_timeout
    )
    budget.charge(ir.cost_usd)
    return ir, _elapsed_ms(t0)


async def _drain_anchor_bounded(
    cand: Any,
    wiki_root: Path,
    today: str,
    invoke: Callable[..., Awaitable[Any]],
    sem: asyncio.Semaphore,
    budget: Any,
    _root: Any,
) -> Any:
    """Drain one anchor candidate under semaphore + budget control."""
    gap = f"anchor:{cand.scope_name}"
    async with sem:
        if budget.exhausted():
            return _drain_result(
                cand.suggested_path, gap, "skipped", 0, "budget exhausted", _root
            )
        ir, ms = await _invoke_anchor_call(cand, invoke, budget, _root)
        if not ir.text or ir.text.strip() == "":
            return _drain_result(
                cand.suggested_path, gap, "failed", ms, "claude returned empty", _root
            )
        written = await _write_anchor_page(
            wiki_root=wiki_root,
            domain=cand.domain,
            scope_name=cand.scope_name,
            suggested_kind=cand.suggested_kind,
            suggested_path=cand.suggested_path,
            body_markdown=ir.text.strip(),
            today=today,
        )
        return _drain_result(
            str(written) if written else cand.suggested_path,
            gap,
            "filled" if written else "failed",
            ms,
            "" if written else "page write failed",
            _root,
        )


def _make_charging_invoke(
    invoke: Callable[..., Awaitable[Any]], budget: Any, _root: Any
) -> Callable[..., Awaitable[Any]]:
    """Wrap ``invoke`` to auto-charge the budget and inject the effective timeout."""

    async def charging_invoke(prompt: str, **kw: Any) -> Any:
        kw.setdefault(
            "timeout",
            max(1.0, min(float(_root.CLAUDE_CALL_TIMEOUT_SEC), budget.time_left())),
        )
        ir = await invoke(prompt, **kw)
        budget.charge(ir.cost_usd)
        return ir

    return charging_invoke


async def _drain_page_bounded(
    page_path: Path,
    meta: dict[str, Any],
    body: str,
    wiki_root: Path,
    invoke: Callable[..., Awaitable[Any]],
    sem: asyncio.Semaphore,
    budget: Any,
    _root: Any,
) -> list[Any]:
    """Drain all gaps on one file page under semaphore + budget control."""
    async with sem:
        if budget.exhausted():
            return [
                _drain_result(page_path, "all", "skipped", 0, "budget exhausted", _root)
            ]
        charging_invoke = _make_charging_invoke(invoke, budget, _root)
        return await drain_all_gaps_on_page(
            page_path, meta, body, wiki_root=wiki_root, invoke=charging_invoke
        )


async def _gather_cycle_results(
    anchor_cands: list[Any],
    file_cands: list[tuple[Path, dict[str, Any], str]],
    wiki_root: Path,
    today: str,
    invoke: Callable[..., Awaitable[Any]],
    sem: asyncio.Semaphore,
    budget: Any,
    _root: Any,
) -> tuple[list[Any], list[Any]]:
    """Phase 3: scatter every candidate concurrently under sem + budget."""
    anchor_coros = [
        _drain_anchor_bounded(c, wiki_root, today, invoke, sem, budget, _root)
        for c in anchor_cands
    ]
    page_coros = [
        _drain_page_bounded(p, m, b, wiki_root, invoke, sem, budget, _root)
        for p, m, b in file_cands
    ]
    anchor_results = list(await asyncio.gather(*anchor_coros)) if anchor_coros else []
    page_results_nested = list(await asyncio.gather(*page_coros)) if page_coros else []
    file_results = [r for nested in page_results_nested for r in nested]
    return anchor_results, file_results


def _summarize_cycle(
    cycle_start: float,
    file_cands_raw: list[Any],
    file_cands: list[Any],
    anchor_results: list[Any],
    file_results: list[Any],
    budget: Any,
    _root: Any,
) -> Any:
    """Phase 4: aggregate anchor + file results into a CycleSummary."""
    all_results = anchor_results + file_results
    filled = sum(1 for r in all_results if r.status == "filled")
    failed = sum(1 for r in all_results if r.status == "failed")
    skipped_budget = sum(
        1
        for r in all_results
        if r.status == "skipped" and r.detail == "budget exhausted"
    )
    # "attempted" means an invoke was actually issued — a skipped candidate
    # (budget exhausted before its turn) never called claude, so it does not
    # count as an attempt. filled + failed are the only attempted outcomes.
    drains_attempted = sum(1 for r in all_results if r.status != "skipped")
    wall_ms = _elapsed_ms(cycle_start)

    return _root.CycleSummary(
        pages_scanned=len(file_cands_raw),
        pages_with_gaps=len(file_cands),
        drains_attempted=drains_attempted,
        drains_filled=filled,
        drains_failed=failed,
        duration_ms=wall_ms,
        results=all_results,
        usd_spent=budget.usd_spent,
        wall_clock_ms=wall_ms,
        skipped_budget=skipped_budget,
    )


def _build_cycle_budget_and_sem(_root: Any) -> tuple[Any, asyncio.Semaphore]:
    """Construct the per-cycle budget tracker and concurrency semaphore."""
    budget = _root.CycleBudget(
        deadline=time.monotonic() + _root.CORTEX_HEADLESS_BUDGET_SEC,
        usd_cap=_root.CORTEX_HEADLESS_USD_BUDGET,
    )
    return budget, asyncio.Semaphore(_root.CORTEX_HEADLESS_CONCURRENCY)


async def _execute_cycle(
    wiki_root: Path,
    max_drains: int,
    max_anchor_drains: int,
    invoke: Callable[..., Awaitable[Any]],
    cycle_start: float,
    _root: Any,
) -> Any:
    """Build candidates, run them concurrently, and summarize the cycle."""
    today = datetime.now(timezone.utc).date().isoformat()
    budget, sem = _build_cycle_budget_and_sem(_root)
    anchor_cands, file_cands, file_cands_raw = _build_cycle_candidates(
        wiki_root, max_drains, max_anchor_drains, _root
    )
    anchor_results, file_results = await _gather_cycle_results(
        anchor_cands, file_cands, wiki_root, today, invoke, sem, budget, _root
    )
    return _summarize_cycle(
        cycle_start,
        file_cands_raw,
        file_cands,
        anchor_results,
        file_results,
        budget,
        _root,
    )


async def run_headless_authoring_cycle(
    wiki_root: Path | None = None,
    *,
    max_drains: int | None = None,
    max_anchor_drains: int | None = None,
    invoke: Callable[..., Awaitable[Any]] | None = None,
) -> Any:
    """One autonomous cycle: author missing anchor pages, then drain
    file-doc gaps, concurrently under a shared semaphore + per-cycle
    budget. Anchor pages first (more visibly incomplete than one
    missing file-doc section). Invariant: <=CORTEX_HEADLESS_CONCURRENCY
    in-flight calls.
    """
    # Deferred import (issue #237): see module docstring's import-cycle note.
    from . import headless_authoring as _root  # noqa: PLC0415 — import cycle (partner: headless_authoring, #237)

    # Stays inline: _root's concrete type here is what lets pyright narrow
    # away `| None` (an extracted helper taking `_root: Any` cannot).
    if max_drains is None:
        max_drains = _root.CORTEX_HEADLESS_MAX_FILE_DRAINS
    if max_anchor_drains is None:
        max_anchor_drains = _root.CORTEX_HEADLESS_MAX_ANCHOR_DRAINS
    if invoke is None:
        invoke = _root._claude_invoke
    if wiki_root is None:
        wiki_root = Path(WIKI_ROOT)

    cycle_start = time.monotonic()
    return await _execute_cycle(
        wiki_root, max_drains, max_anchor_drains, invoke, cycle_start, _root
    )
