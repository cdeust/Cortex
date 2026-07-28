"""Drain operations for the headless authoring worker.

Per-page and per-anchor drain routines that issue ``claude -p`` calls
and rewrite wiki pages. Split out of ``headless_authoring`` to keep
that module under the size limit (Fowler: Move Function). The public
import surface remains ``headless_authoring``; these names are
re-exported there.

Patchability contract: the default ``invoke`` and the dataclass types
are read from the root module so that the re-exported references stay
identical to the public ones. ``_claude_invoke`` is not monkeypatched
in tests (callers pass ``invoke`` explicitly), so binding the default
at import time preserves the original behaviour.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from . import headless_authoring as _root
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

from .page_io import (
    _project_source_for_page,
    _rewrite_page,
    _scope_anchor_prompt,
    _write_anchor_page,
)


def _optional_source_root(meta: dict[str, Any]) -> str | None:
    """Resolve source_root for --add-dir scope extension (audit B-1).

    NOTE: --add-dir extends readable scope; it does NOT confine reads.
    Returns None when the domain is absent or resolution fails — the
    drain proceeds without the extra scope either way.
    """
    domain = meta.get("domain")
    if not domain or not isinstance(domain, str):
        return None
    try:
        from mcp_server.core.wiki_coverage import _project_source_root

        return _project_source_root(domain)
    except Exception as exc:  # noqa: BLE001 — source-root scope is optional enrichment
        silent_failure.note("consolidation.project_source_root", exc)
        return None


async def drain_one(
    page_path: Path,
    meta: dict[str, Any],
    body: str,
    *,
    wiki_root: Path,
    invoke: Callable[..., Awaitable[Any]] = _root._claude_invoke,
) -> Any:
    """Drain the first curation gap on one page (legacy single-section path).

    Pre-condition:  ``page_path`` is a valid wiki page under ``wiki_root``;
                    ``meta`` is parsed
                    frontmatter; ``body`` is the page body.
    Post-condition: the gap marker is replaced in the file on disk and the
                    result reflects the outcome (filled/failed/skipped).
    """
    start = time.monotonic()
    gaps = meta.get("curation_gaps") or []
    if not gaps:
        return _root.DrainResult(
            page_path=str(page_path),
            gap="",
            status="skipped",
            duration_ms=0,
            detail="no gaps",
        )

    gap_name = gaps[0]
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
    response = ir.text
    if response is None or response.strip() == "":
        return _root.DrainResult(
            page_path=str(page_path),
            gap=gap_name,
            status="failed",
            duration_ms=int((time.monotonic() - start) * 1000),
            detail="claude invocation failed",
        )
    response_stripped = response.strip()
    if response_stripped.upper().startswith("NO INFORMATION AVAILABLE"):
        new_body, did = _replace_gap_marker(
            body, gap_desc, "_(no information available for this section)_"
        )
    else:
        new_body, did = _replace_gap_marker(body, gap_desc, response_stripped)
    if not did:
        return _root.DrainResult(
            page_path=str(page_path),
            gap=gap_name,
            status="failed",
            duration_ms=int((time.monotonic() - start) * 1000),
            detail="gap marker not found in body",
        )
    new_gaps = [g for g in gaps if g != gap_name]
    ok = await _rewrite_page(
        page_path, wiki_root, new_body=new_body, new_curation_gaps=new_gaps
    )
    return _root.DrainResult(
        page_path=str(page_path),
        gap=gap_name,
        status="filled" if ok else "failed",
        duration_ms=int((time.monotonic() - start) * 1000),
        detail="" if ok else "page rewrite failed",
    )


# ── Whole-page drain (drain_all_gaps_on_page) ──────────────────────
#
# The single-section drain (above) was the proof of concept. The
# bulk-drain below issues ONE ``claude -p`` call per page that fills
# EVERY missing section in one response — about 7-8× faster per
# page, gives the LLM the full picture so cross-references between
# sections stay coherent, and lets one autonomous cycle materially
# move the 14k-gap backlog instead of nibbling at it.


async def drain_all_gaps_on_page(
    page_path: Path,
    meta: dict[str, Any],
    body: str,
    *,
    wiki_root: Path,
    invoke: Callable[..., Awaitable[Any]] = _root._claude_invoke,
) -> list[Any]:
    """Fill every curation gap on one page in a single ``claude -p`` call.

    Returns one DrainResult per gap so the cycle summary still
    accounts for each individually. A failure on one gap leaves the
    others' fills intact — the parser tolerates missing delimiters,
    so partial responses still make progress.

    The gap set is computed by LIVE AUDIT (not the frozen frontmatter
    list) so newly-added canonical sections — sequence diagram,
    parameters, request/response examples — get filled on pages that
    already exist.

    Pre-condition:  ``page_path`` is a wiki page with curation gaps under
                    ``wiki_root``; ``invoke`` is an async callable matching
                    ``_claude_invoke``'s signature.
    Post-condition: all filled sections are written to disk through the
                    governed wiki-write path (write_class='mechanical'
                    pointer memory + citation sync — see
                    ``write_governed_page``); returned list has one
                    DrainResult per gap (filled/failed).
    """
    start = time.monotonic()
    frozen = [g for g in (meta.get("curation_gaps") or []) if isinstance(g, str)]
    gaps = _live_audit_gaps(body, frozen)
    if not gaps:
        return []

    src_root = _optional_source_root(meta)
    _, source_text = _project_source_for_page(meta)
    prompt = _build_page_prompt(
        page_path=str(page_path),
        page_meta=meta,
        gaps=gaps,
        source_text=source_text,
        delegate_hint=_root._delegation_hint_for(meta.get("kind") or "file-doc"),
    )
    ir = await invoke(prompt, source_root=src_root)
    base_ms = int((time.monotonic() - start) * 1000)
    response = ir.text
    if not response:
        return [
            _root.DrainResult(
                page_path=str(page_path),
                gap=g,
                status="failed",
                duration_ms=base_ms,
                detail="claude invocation failed",
            )
            for g in gaps
        ]

    filled_map = _parse_sectioned_response(response, gaps)
    new_body = body
    filled_gaps: list[str] = []
    results: list[Any] = []
    for g in gaps:
        content = filled_map.get(g)
        gap_desc = _GAP_DESCRIPTIONS.get(g) or g
        if not content:
            results.append(
                _root.DrainResult(
                    page_path=str(page_path),
                    gap=g,
                    status="failed",
                    duration_ms=base_ms,
                    detail="not in response",
                )
            )
            continue
        if content.upper().startswith("NO INFORMATION AVAILABLE"):
            content = "_(no information available for this section)_"
        new_body, did = _replace_gap_marker(new_body, gap_desc, content)
        if not did:
            results.append(
                _root.DrainResult(
                    page_path=str(page_path),
                    gap=g,
                    status="failed",
                    duration_ms=base_ms,
                    detail="marker not found",
                )
            )
            continue
        filled_gaps.append(g)
        results.append(
            _root.DrainResult(
                page_path=str(page_path),
                gap=g,
                status="filled",
                duration_ms=base_ms,
                detail="",
            )
        )
    if filled_gaps:
        remaining = [g for g in gaps if g not in filled_gaps]
        wrote = await _rewrite_page(
            page_path, wiki_root, new_body=new_body, new_curation_gaps=remaining
        )
        if not wrote:
            # The governed write failed after content was successfully parsed
            # out of the response — downgrade the optimistic "filled" results
            # for this page to "failed" so the cycle summary (and any caller
            # counting drains_filled) reflects reality, not the parse step.
            for r in results:
                if r.gap in filled_gaps:
                    r.status = "failed"
                    r.detail = "governed write failed"
    return results


# ── Anchor-page authoring path ─────────────────────────────────────
#
# A project that's missing its architecture / services / api / ci-cd
# / mcp / ai-usage / prd / decisions anchor pages doesn't have any
# gap markers to drain — the pages simply don't exist. The fix is
# the symmetric move: detect missing anchors via the coverage audit,
# feed Claude a project-level overview (file tree, README, key
# config files, source file counts), and ask it to author the
# anchor from scratch.
#
# 285 anchors total (15 scopes × 19 projects); these drain in one
# autonomous run because each anchor is one ``claude -p`` call.


async def drain_missing_anchors(
    wiki_root: Path,
    *,
    max_drains: int = 30,
    today: str | None = None,
    invoke: Callable[..., Awaitable[Any]] = _root._claude_invoke,
) -> list[Any]:
    """Author missing canonical anchor pages for every project.

    For each domain × scope combination with no covered anchor, calls
    ``claude -p`` with a project-level context block and writes the
    response as the new anchor page. Up to ``max_drains`` authored per
    invocation so a single cycle stays time-bounded.

    Piece 3 — Groundable-only filter: scopes marked ``groundable=False``
    in ``wiki_coverage.SCOPES`` (e.g. prd, decisions, changelog, roadmap,
    accessibility, localization) are skipped entirely — their content
    cannot be derived by reading the source tree and autonomous authoring
    would be fabrication (zetetic-forbidden). They remain visible as
    coverage gaps for human authors.

    Pre-condition:  ``wiki_root`` is a valid directory; ``invoke`` is an
                    async callable matching ``_claude_invoke``'s signature.
    Post-condition: up to ``max_drains`` new anchor pages written to disk;
                    ungroundable scopes are omitted (not skipped-with-result).
    """
    from datetime import datetime, timezone

    from mcp_server.core.wiki_coverage import (
        _project_source_root,
        audit_domain,
    )
    from mcp_server.shared.domain_mapping import _build_registry

    today = today or datetime.now(timezone.utc).date().isoformat()
    domains = sorted({r.canonical for r in _build_registry().repos})

    results: list[Any] = []
    for domain in domains:
        if len([r for r in results if r.status == "filled"]) >= max_drains:
            break
        src_root = _project_source_root(domain)
        if not src_root:
            continue
        cov = audit_domain(str(wiki_root), domain)
        for sc in cov.scopes:
            if sc.covered:
                continue
            # Piece 3: skip ungroundable scopes — content cannot be
            # derived from source tree alone; autonomous authoring would
            # fabricate rather than document.
            if not sc.scope.groundable:
                continue
            if len([r for r in results if r.status == "filled"]) >= max_drains:
                break
            t0 = time.monotonic()
            prompt = _scope_anchor_prompt(
                domain=domain,
                scope_name=sc.scope.name,
                scope_title=sc.scope.title,
                scope_description=sc.scope.description,
                source_root=src_root,
                delegate_hint=_root._delegation_hint_for(sc.scope.suggested_kind),
            )
            ir = await invoke(prompt, cwd=src_root, source_root=src_root)
            response = ir.text
            if not response or response.strip() == "":
                results.append(
                    _root.DrainResult(
                        page_path=sc.suggested_path,
                        gap=f"anchor:{sc.scope.name}",
                        status="failed",
                        duration_ms=int((time.monotonic() - t0) * 1000),
                        detail="claude returned empty",
                    )
                )
                continue
            written = await _write_anchor_page(
                wiki_root=wiki_root,
                domain=domain,
                scope_name=sc.scope.name,
                suggested_kind=sc.scope.suggested_kind,
                suggested_path=sc.suggested_path,
                body_markdown=response.strip(),
                today=today,
            )
            results.append(
                _root.DrainResult(
                    page_path=str(written) if written else sc.suggested_path,
                    gap=f"anchor:{sc.scope.name}",
                    status="filled" if written else "failed",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    detail="" if written else "page write failed",
                )
            )
    return results
