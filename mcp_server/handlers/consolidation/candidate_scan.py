"""Candidate discovery for the headless authoring worker (no LLM calls).

Walks the wiki for pages with curation gaps and scans projects for
missing groundable anchor pages. Split out of ``headless_authoring``
to keep that module under the size limit (Fowler: Move Function).

Patchability contract: ``run_headless_authoring_cycle`` resolves
``_scan_pages_with_gaps`` and ``_collect_anchor_candidates`` at call
time as attributes of the ``headless_authoring`` module (where they
are re-exported), so tests that ``monkeypatch.setattr(ha, ...)`` are
observed. ``_AnchorCandidate`` is read from the root module the same
way so the constructed type matches the re-exported one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .page_io import _parse_frontmatter
from mcp_server.observability import silent_failure
from mcp_server.core.wiki_coverage import _project_source_root, audit_domain
from mcp_server.shared.domain_mapping import _build_registry


def _scan_pages_with_gaps(wiki_root: Path) -> list[tuple[Path, dict[str, Any], str]]:
    """Walk the wiki and return ``(path, meta, body)`` for pages with gaps.

    A page is "with gaps" when EITHER the frontmatter declares
    ``curation_gaps`` non-empty OR a live audit of the body shows
    missing canonical sections. The second axis catches pages that
    were complete under the old section catalogue but are incomplete
    after the catalogue gained new sections (e.g. sequence-diagram,
    parameters, request-example, response-example added 2026-05-18).

    Only pages classified as kind=reference / explanation file-docs
    are audited live; ADRs / specs / guides have their own section
    sets and shouldn't be force-fed file-doc sections.
    """
    if not wiki_root.is_dir():
        return []
    # Lazy import to keep this module self-contained.
    try:
        from mcp_server.core.wiki_curation_gaps import missing_sections  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        missing_sections = None  # type: ignore[assignment]

    out: list[tuple[Path, dict[str, Any], str]] = []
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if any(part.startswith((".", "_")) for part in rel.parts):
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        meta, body, _ = _parse_frontmatter(text)
        gaps = meta.get("curation_gaps")
        if isinstance(gaps, list) and gaps:
            out.append((md, meta, body))
            continue
        # No frozen gaps — but a file-doc might still be missing
        # sections that were added to the catalogue after generation.
        # Only force-audit file-docs (kind=reference + has source_file_path).
        if (
            missing_sections is not None
            and meta.get("kind") == "reference"
            and meta.get("source_file_path")
        ):
            try:
                live = missing_sections(body)
            except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
                silent_failure.note("candidate_scan.live_audit", exc)
                live = []
            if live:
                out.append((md, meta, body))
    return out


def _collect_anchor_candidates(
    wiki_root: Path,
    max_drains: int,
) -> list[Any]:
    """Scan for missing groundable anchor candidates without calling claude.

    Pre-condition:  ``wiki_root`` is an existing directory; ``max_drains`` > 0.
    Post-condition: returned list has at most ``max_drains`` items, each
                    representing a missing scope that passes the groundable
                    filter and has a resolvable source root.
    """
    # Deferred import (issue #237): headless_authoring imports this function
    # back at load time, so a module-top-level `from . import
    # headless_authoring` here would deadlock a fresh interpreter that
    # imports candidate_scan before headless_authoring finishes initializing.
    # Resolved at call time instead — the constructed type still matches the
    # re-exported ``headless_authoring._AnchorCandidate`` exactly (same
    # module object, no copy).
    from . import headless_authoring as _root  # noqa: PLC0415 — import cycle (partner: headless_authoring, #237)

    try:
        domains = sorted({r.canonical for r in _build_registry().repos})
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("candidate_scan.registry", exc)
        return []

    candidates: list[Any] = []
    for domain in domains:
        src_root = _project_source_root(domain)
        if not src_root:
            continue
        try:
            cov = audit_domain(str(wiki_root), domain)
        except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
            silent_failure.note("candidate_scan.audit_domain", exc)
            continue
        for sc in cov.scopes:
            if sc.covered:
                continue
            if not sc.scope.groundable:
                continue
            candidates.append(
                _root._AnchorCandidate(
                    domain=domain,
                    scope_name=sc.scope.name,
                    scope_title=sc.scope.title,
                    scope_description=sc.scope.description,
                    source_root=src_root,
                    suggested_path=sc.suggested_path,
                    suggested_kind=sc.scope.suggested_kind,
                )
            )
            if len(candidates) >= max_drains:
                return candidates
    return candidates
