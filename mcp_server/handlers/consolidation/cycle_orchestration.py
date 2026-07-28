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

Split out of ``headless_authoring`` to keep that module under the size
limit (Fowler: Move Function). The public import surface remains
``headless_authoring``; ``run_headless_authoring_cycle`` is re-exported
there.

Patchability contract (the reason this module reads ``_root.X`` instead
of importing the names): the throttle tests do
``monkeypatch.setattr(ha, "CORTEX_HEADLESS_CONCURRENCY", 2)``,
``monkeypatch.setattr(ha, "_collect_anchor_candidates", ...)``, and
``monkeypatch.setattr(ha, "_scan_pages_with_gaps", ...)`` then call
``run_headless_authoring_cycle``. For those patches to be observed,
this function MUST resolve those names at CALL TIME from the
``headless_authoring`` module namespace. The ``from . import
headless_authoring as _root`` below is a deliberate circular import
that works ONLY because we touch ``_root.X`` at call time, never at
import time. Do not change ``_root.X`` accesses to direct imports.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from . import headless_authoring as _root
from .drain_operations import drain_all_gaps_on_page
from .page_io import _scope_anchor_prompt, _write_anchor_page
from datetime import datetime, timezone
from mcp_server.infrastructure.config import WIKI_ROOT


async def run_headless_authoring_cycle(
    wiki_root: Path | None = None,
    *,
    max_drains: int = _root.CORTEX_HEADLESS_MAX_FILE_DRAINS,
    max_anchor_drains: int = _root.CORTEX_HEADLESS_MAX_ANCHOR_DRAINS,
    invoke: Callable[..., Awaitable[Any]] = _root._claude_invoke,
) -> Any:
    """One autonomous cycle: author missing anchor pages, then drain
    file-doc curation gaps.  Runs concurrently under a shared semaphore
    and a per-cycle budget (wall-clock + USD).

    Anchor pages come first — a project missing its
    architecture/services/api page is more visibly incomplete than a
    single file-doc with a missing "Callers" section.

    Pre-condition:  ``invoke`` is an async callable with the signature of
                    ``_claude_invoke``.  ``wiki_root`` resolves to a valid
                    wiki directory.
    Post-condition: CycleSummary reflects all outcomes including budget
                    telemetry (usd_spent, wall_clock_ms, skipped_budget).
    Invariant:      no more than CORTEX_HEADLESS_CONCURRENCY in-flight
                    subprocess calls at any point in the cycle.
    """

    cycle_start = time.monotonic()
    if wiki_root is None:
        wiki_root = Path(WIKI_ROOT)

    today = datetime.now(timezone.utc).date().isoformat()

    budget = _root.CycleBudget(
        deadline=time.monotonic() + _root.CORTEX_HEADLESS_BUDGET_SEC,
        usd_cap=_root.CORTEX_HEADLESS_USD_BUDGET,
    )
    sem = asyncio.Semaphore(_root.CORTEX_HEADLESS_CONCURRENCY)

    # ── Phase 1: build full candidate list (no claude calls) ──────────
    anchor_cands = _root._collect_anchor_candidates(wiki_root, max_anchor_drains)
    file_cands_raw = _root._scan_pages_with_gaps(wiki_root)
    file_cands_raw.sort(
        key=lambda c: (-(len(c[1].get("curation_gaps") or [])), str(c[0]))
    )
    file_cands = file_cands_raw[:max_drains]

    # ── Phase 2: coroutine factories ──────────────────────────────────

    async def drain_anchor_bounded(cand: Any) -> Any:
        """Drain one anchor candidate under semaphore + budget control."""
        async with sem:
            if budget.exhausted():
                return _root.DrainResult(
                    page_path=cand.suggested_path,
                    gap=f"anchor:{cand.scope_name}",
                    status="skipped",
                    duration_ms=0,
                    detail="budget exhausted",
                )
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
                prompt,
                cwd=cand.source_root,
                source_root=cand.source_root,
                timeout=eff_timeout,
            )
            budget.charge(ir.cost_usd)
            ms = int((time.monotonic() - t0) * 1000)
            if not ir.text or ir.text.strip() == "":
                return _root.DrainResult(
                    page_path=cand.suggested_path,
                    gap=f"anchor:{cand.scope_name}",
                    status="failed",
                    duration_ms=ms,
                    detail="claude returned empty",
                )
            written = await _write_anchor_page(
                wiki_root=wiki_root,  # type: ignore[arg-type]
                domain=cand.domain,
                scope_name=cand.scope_name,
                suggested_kind=cand.suggested_kind,
                suggested_path=cand.suggested_path,
                body_markdown=ir.text.strip(),
                today=today,
            )
            return _root.DrainResult(
                page_path=str(written) if written else cand.suggested_path,
                gap=f"anchor:{cand.scope_name}",
                status="filled" if written else "failed",
                duration_ms=ms,
                detail="" if written else "page write failed",
            )

    async def drain_page_bounded(
        page_path: Path, meta: dict[str, Any], body: str
    ) -> list[Any]:
        """Drain all gaps on one file page under semaphore + budget control."""
        async with sem:
            if budget.exhausted():
                return [
                    _root.DrainResult(
                        page_path=str(page_path),
                        gap="all",
                        status="skipped",
                        duration_ms=0,
                        detail="budget exhausted",
                    )
                ]

            # Wrap invoke to auto-charge the budget after each call and
            # inject the effective timeout derived from remaining budget time.
            async def charging_invoke(prompt: str, **kw: Any) -> Any:
                kw.setdefault(
                    "timeout",
                    max(
                        1.0,
                        min(float(_root.CLAUDE_CALL_TIMEOUT_SEC), budget.time_left()),
                    ),
                )
                ir = await invoke(prompt, **kw)
                budget.charge(ir.cost_usd)
                return ir

            return await drain_all_gaps_on_page(
                page_path, meta, body, wiki_root=wiki_root, invoke=charging_invoke
            )

    # ── Phase 3: gather all candidates concurrently ───────────────────
    anchor_coros = [drain_anchor_bounded(c) for c in anchor_cands]
    page_coros = [drain_page_bounded(p, m, b) for p, m, b in file_cands]

    anchor_results: list[Any] = (
        list(await asyncio.gather(*anchor_coros)) if anchor_coros else []
    )
    page_results_nested: list[list[Any]] = (
        list(await asyncio.gather(*page_coros)) if page_coros else []
    )
    file_results: list[Any] = [r for nested in page_results_nested for r in nested]

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
    wall_ms = int((time.monotonic() - cycle_start) * 1000)

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
