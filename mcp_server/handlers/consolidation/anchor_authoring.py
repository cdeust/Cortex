"""Anchor-page authoring for the headless authoring worker.

A project missing its architecture / services / api / ci-cd / mcp /
ai-usage / prd / decisions anchor page has no gap marker to drain — the
page simply doesn't exist. This module detects missing anchors via the
coverage audit, feeds Claude a project-level overview (file tree,
README, key config files, source file counts), and asks it to author
the anchor from scratch. Split out of ``drain_operations`` (Fowler:
Move Function, issue #276) to keep that module under the size limit;
the public import surface stays ``headless_authoring``, which
re-exports ``drain_missing_anchors``.

Import-cycle note (issue #237 family): a module-top ``from . import
headless_authoring as _root`` would deadlock a fresh interpreter
importing this module before ``headless_authoring`` finishes (it
imports ``drain_missing_anchors`` back at load time). ``_root`` is
resolved lazily at call time instead — every
``monkeypatch.setattr(headless_authoring, ...)`` stays observed.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .drain_operations import _drain_result, _elapsed_ms
from .page_io import _scope_anchor_prompt, _write_anchor_page
from mcp_server.core.wiki_coverage import _project_source_root, audit_domain
from mcp_server.shared.domain_mapping import _build_registry


def _filled_count(results: list[Any]) -> int:
    """Count how many DrainResults in ``results`` have status='filled'."""
    return len([r for r in results if r.status == "filled"])


async def _invoke_anchor_fill(
    domain: str,
    sc: Any,
    src_root: str,
    invoke: Callable[..., Awaitable[Any]],
    _root: Any,
) -> tuple[Any, int]:
    """Build the anchor prompt, invoke claude, return (ir, elapsed_ms)."""
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
    return ir, _elapsed_ms(t0)


async def _author_one_anchor(
    domain: str,
    sc: Any,
    src_root: str,
    wiki_root: Path,
    today: str,
    invoke: Callable[..., Awaitable[Any]],
    _root: Any,
) -> Any:
    """Invoke claude for one missing anchor scope and write the result page."""
    gap = f"anchor:{sc.scope.name}"
    ir, ms = await _invoke_anchor_fill(domain, sc, src_root, invoke, _root)
    response = ir.text
    if not response or response.strip() == "":
        return _drain_result(
            sc.suggested_path, gap, "failed", ms, "claude returned empty", _root
        )
    written = await _write_anchor_page(
        wiki_root=wiki_root,
        domain=domain,
        scope_name=sc.scope.name,
        suggested_kind=sc.scope.suggested_kind,
        suggested_path=sc.suggested_path,
        body_markdown=response.strip(),
        today=today,
    )
    return _drain_result(
        str(written) if written else sc.suggested_path,
        gap,
        "filled" if written else "failed",
        ms,
        "" if written else "page write failed",
        _root,
    )


async def _drain_domain_anchors(
    domain: str,
    wiki_root: Path,
    max_drains: int,
    today: str,
    invoke: Callable[..., Awaitable[Any]],
    results: list[Any],
    _root: Any,
) -> None:
    """Author missing anchors for one domain, appending to ``results`` in place."""
    src_root = _project_source_root(domain)
    if not src_root:
        return
    cov = audit_domain(str(wiki_root), domain)
    for sc in cov.scopes:
        if sc.covered:
            continue
        # Groundable-only filter: content that can't be derived from the
        # source tree alone (prd, decisions, changelog, roadmap, ...) is
        # skipped entirely rather than fabricated (zetetic-forbidden).
        if not sc.scope.groundable:
            continue
        if _filled_count(results) >= max_drains:
            break
        results.append(
            await _author_one_anchor(
                domain, sc, src_root, wiki_root, today, invoke, _root
            )
        )


async def drain_missing_anchors(
    wiki_root: Path,
    *,
    max_drains: int = 30,
    today: str | None = None,
    invoke: Callable[..., Awaitable[Any]] | None = None,
) -> list[Any]:
    """Author missing canonical anchor pages for every project.

    For each domain x scope combination with no covered anchor, calls
    ``claude -p`` with a project-level context block and writes the
    response as the new anchor page. Up to ``max_drains`` authored per
    invocation so a single cycle stays time-bounded. Ungroundable
    scopes are omitted (not skipped-with-result) — they remain visible
    as coverage gaps for human authors.

    Pre: ``wiki_root`` is a valid directory; ``invoke`` matches
    ``_claude_invoke``'s signature.
    Post: up to ``max_drains`` new anchor pages written to disk.
    """
    # Deferred import (issue #237): see module docstring's import-cycle note.
    from . import headless_authoring as _root  # noqa: PLC0415 — import cycle (partner: headless_authoring, #237)

    if invoke is None:
        invoke = _root._claude_invoke

    today = today or datetime.now(timezone.utc).date().isoformat()
    domains = sorted({r.canonical for r in _build_registry().repos})

    results: list[Any] = []
    for domain in domains:
        if _filled_count(results) >= max_drains:
            break
        await _drain_domain_anchors(
            domain, wiki_root, max_drains, today, invoke, results, _root
        )
    return results
