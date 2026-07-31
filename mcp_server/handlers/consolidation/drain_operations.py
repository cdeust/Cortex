"""Per-page drain routines for the headless authoring worker.

Issues ``claude -p`` calls and rewrites wiki pages. Split out of
``headless_authoring`` (Fowler: Move Function); anchor-page authoring
is a separate concern, split further into ``anchor_authoring`` (issue
#276). The public import surface stays ``headless_authoring``, which
these names re-export.

Import-cycle note (issue #237): a module-top ``from . import
headless_authoring as _root`` would deadlock a fresh interpreter
importing this module before ``headless_authoring`` finishes (it
imports these functions back at load time). Each function resolves
``_root`` lazily at call time instead — every
``monkeypatch.setattr(headless_authoring, ...)`` stays observed.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .authoring_prompts import (
    _GAP_DESCRIPTIONS,
    _build_page_prompt,
    _build_section_prompt,
    _gap_heading,
    _live_audit_gaps,
    _parse_sectioned_response,
    _replace_gap_marker,
)
from mcp_server.observability import silent_failure

from .page_io import _project_source_for_page, _rewrite_page
from mcp_server.core.wiki_coverage import _project_source_root


def _optional_source_root(meta: dict[str, Any]) -> str | None:
    """Resolve source_root for --add-dir scope extension (audit B-1).

    --add-dir extends readable scope; it does NOT confine reads. Returns
    None when the domain is absent or resolution fails (drain proceeds
    without the extra scope either way).
    """
    domain = meta.get("domain")
    if not domain or not isinstance(domain, str):
        return None
    try:
        return _project_source_root(domain)
    except Exception as exc:  # noqa: BLE001 — source-root scope is optional enrichment
        silent_failure.note("consolidation.project_source_root", exc)
        return None


def _elapsed_ms(start: float) -> int:
    """Milliseconds elapsed since ``start`` (a ``time.monotonic()`` value)."""
    return int((time.monotonic() - start) * 1000)


def _drain_result(
    page_path: Path | str,
    gap: str,
    status: str,
    duration_ms: int,
    detail: str,
    _root: Any,
) -> Any:
    """Build one DrainResult — the shared return shape for every drain step."""
    return _root.DrainResult(
        page_path=str(page_path),
        gap=gap,
        status=status,
        duration_ms=duration_ms,
        detail=detail,
    )


async def _finish_drain_one(
    ir: Any,
    page_path: Path,
    body: str,
    wiki_root: Path,
    gaps: list[str],
    gap_name: str,
    gap_desc: str,
    start: float,
    _root: Any,
) -> Any:
    """Apply ``drain_one``'s claude response to the page body and persist it."""

    def result(status: str, detail: str) -> Any:
        return _drain_result(
            page_path, gap_name, status, _elapsed_ms(start), detail, _root
        )

    response = ir.text
    if response is None or response.strip() == "":
        return result("failed", "claude invocation failed")
    response_stripped = response.strip()
    if response_stripped.upper().startswith("NO INFORMATION AVAILABLE"):
        new_body, did = _replace_gap_marker(
            body, gap_desc, "_(no information available for this section)_"
        )
    else:
        new_body, did = _replace_gap_marker(body, gap_desc, response_stripped)
    if not did:
        return result("failed", "gap marker not found in body")
    new_gaps = [g for g in gaps if g != gap_name]
    ok = await _rewrite_page(
        page_path, wiki_root, new_body=new_body, new_curation_gaps=new_gaps
    )
    return result("filled" if ok else "failed", "" if ok else "page rewrite failed")


async def _invoke_section_fill(
    page_path: Path,
    meta: dict[str, Any],
    gap_name: str,
    invoke: Callable[..., Awaitable[Any]],
    _root: Any,
) -> tuple[Any, str]:
    """Build the single-section fill prompt, invoke claude, return (ir, gap_desc)."""
    gap_desc = _GAP_DESCRIPTIONS.get(gap_name) or gap_name
    _, source_text = _project_source_for_page(meta)
    src_root = _optional_source_root(meta)
    prompt = _build_section_prompt(
        page_path=str(page_path),
        page_meta=meta,
        gap_name=_gap_heading(gap_name),
        gap_description=gap_desc,
        source_text=source_text,
        delegate_hint=_root._delegation_hint_for(meta.get("kind") or "file-doc"),
    )
    ir = await invoke(prompt, source_root=src_root)
    return ir, gap_desc


async def drain_one(
    page_path: Path,
    meta: dict[str, Any],
    body: str,
    *,
    wiki_root: Path,
    invoke: Callable[..., Awaitable[Any]] | None = None,
) -> Any:
    """Drain the first curation gap on one page (legacy single-section path).

    Pre: ``page_path`` is a valid wiki page under ``wiki_root``; ``meta``
    is parsed frontmatter; ``body`` is the page body.
    Post: the gap marker is replaced on disk; result reflects the outcome
    (filled/failed/skipped).
    """
    # Deferred import (issue #237): see module docstring's import-cycle note.
    from . import headless_authoring as _root  # noqa: PLC0415 — import cycle (partner: headless_authoring, #237)

    if invoke is None:
        invoke = _root._claude_invoke

    start = time.monotonic()
    gaps = meta.get("curation_gaps") or []
    if not gaps:
        return _drain_result(page_path, "", "skipped", 0, "no gaps", _root)

    gap_name = gaps[0]
    ir, gap_desc = await _invoke_section_fill(page_path, meta, gap_name, invoke, _root)
    return await _finish_drain_one(
        ir, page_path, body, wiki_root, gaps, gap_name, gap_desc, start, _root
    )


def _fill_gaps_from_response(
    response: str,
    gaps: list[str],
    body: str,
    page_path: Path,
    base_ms: int,
    _root: Any,
) -> tuple[str, list[str], list[Any]]:
    """Parse the sectioned response and apply each fill to the page body.

    Returns ``(new_body, filled_gaps, results)`` — one DrainResult per gap.
    """

    def result(gap: str, status: str, detail: str) -> Any:
        return _drain_result(page_path, gap, status, base_ms, detail, _root)

    filled_map = _parse_sectioned_response(response, gaps)
    new_body = body
    filled_gaps: list[str] = []
    results: list[Any] = []
    for g in gaps:
        content = filled_map.get(g)
        gap_desc = _GAP_DESCRIPTIONS.get(g) or g
        if not content:
            results.append(result(g, "failed", "not in response"))
            continue
        if content.upper().startswith("NO INFORMATION AVAILABLE"):
            content = "_(no information available for this section)_"
        new_body, did = _replace_gap_marker(new_body, gap_desc, content)
        if not did:
            results.append(result(g, "failed", "marker not found"))
            continue
        filled_gaps.append(g)
        results.append(result(g, "filled", ""))
    return new_body, filled_gaps, results


async def _persist_filled_gaps(
    page_path: Path,
    wiki_root: Path,
    new_body: str,
    gaps: list[str],
    filled_gaps: list[str],
    results: list[Any],
) -> None:
    """Write remaining gaps; downgrade results to "failed" if the write fails."""
    remaining = [g for g in gaps if g not in filled_gaps]
    wrote = await _rewrite_page(
        page_path, wiki_root, new_body=new_body, new_curation_gaps=remaining
    )
    if not wrote:
        for r in results:
            if r.gap in filled_gaps:
                r.status = "failed"
                r.detail = "governed write failed"


async def _invoke_page_fill(
    meta: dict[str, Any],
    gaps: list[str],
    invoke: Callable[..., Awaitable[Any]],
    _root: Any,
) -> tuple[Any, int]:
    """Build the whole-page fill prompt, invoke claude, return (ir, elapsed_ms).

    issue #239 ARG cleanup: a ``page_path`` parameter was accepted and
    forwarded to ``_build_page_prompt(page_path=...)``, but that callee
    never read it either (see its own docstring) — removed here too so no
    unused parameter was left behind by fixing the callee alone. The one
    caller (``drain_page``) still holds and uses ``page_path`` itself for
    its other calls; only this pass-through was dead.
    """
    start = time.monotonic()
    src_root = _optional_source_root(meta)
    _, source_text = _project_source_for_page(meta)
    prompt = _build_page_prompt(
        page_meta=meta,
        gaps=gaps,
        source_text=source_text,
        delegate_hint=_root._delegation_hint_for(meta.get("kind") or "file-doc"),
    )
    ir = await invoke(prompt, source_root=src_root)
    return ir, _elapsed_ms(start)


def _no_response_results(
    page_path: Path, gaps: list[str], base_ms: int, _root: Any
) -> list[Any]:
    """DrainResults for a page whose ``claude -p`` call returned no text."""
    return [
        _drain_result(
            page_path, g, "failed", base_ms, "claude invocation failed", _root
        )
        for g in gaps
    ]


async def drain_all_gaps_on_page(
    page_path: Path,
    meta: dict[str, Any],
    body: str,
    *,
    wiki_root: Path,
    invoke: Callable[..., Awaitable[Any]] | None = None,
) -> list[Any]:
    """Fill every curation gap on one page in a single ``claude -p`` call.

    One request/page (vs. ``drain_one``'s one/gap) is ~7-8x faster and
    keeps cross-references coherent; gap set is a LIVE AUDIT. One
    DrainResult per gap; a failure on one gap leaves others intact.
    """
    # Deferred import (issue #237): see module docstring's import-cycle note.
    from . import headless_authoring as _root  # noqa: PLC0415 — import cycle (partner: headless_authoring, #237)

    if invoke is None:
        invoke = _root._claude_invoke

    frozen = [g for g in (meta.get("curation_gaps") or []) if isinstance(g, str)]
    gaps = _live_audit_gaps(body, frozen)
    if not gaps:
        return []

    ir, base_ms = await _invoke_page_fill(meta, gaps, invoke, _root)
    response = ir.text
    if not response:
        return _no_response_results(page_path, gaps, base_ms, _root)

    new_body, filled_gaps, results = _fill_gaps_from_response(
        response, gaps, body, page_path, base_ms, _root
    )
    if filled_gaps:
        await _persist_filled_gaps(
            page_path, wiki_root, new_body, gaps, filled_gaps, results
        )
    return results
