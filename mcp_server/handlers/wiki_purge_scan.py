"""The tree walk behind ``wiki_purge``: what is a page, and does it stay.

Split out of ``wiki_purge.py`` when the scan accounting for issue #622
pushed that file further past the 300-line cap. The seam is real rather
than arbitrary: this module decides what the wiki holds and which pages
fail which reject axis; ``wiki_purge`` owns the tool contract, the
deletions and the report.

source: ADR-0465"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_server.core.wiki_classifier import classify_memory
from mcp_server.core.wiki_stub_detector import is_shallow, is_stub, stub_score
from mcp_server.shared.wiki_layout import PAGE_KINDS
from mcp_server.shared.yaml_parser import parse_yaml_frontmatter

# Directories that hold authored page-kind content. Derived from the
# path contract in ``shared.wiki_layout`` rather than re-listed here:
# a hand-kept copy had drifted and silently skipped every page under a
# kind it had never heard of — ``rfc`` among them, which the memory→page
# pass emits (issue #622, the ADR-1077 hardcoded-copy pattern).
# Anything else under the wiki root (_kinds, _rules, _views,
# _bibliography, _triggers, .generated) is deliberately left alone.
PAGE_DIRS: frozenset[str] = frozenset(PAGE_KINDS)

# A page lives at ``<kind>/.../<file>.md``; a bare ``README.md`` at the
# root is not a page and has no kind directory to classify it by.
# source: ADR-0682
MIN_PAGE_PARTS = 2


@dataclass
class Census:
    """What the tree walk saw, beyond the pages it evaluated.

    ``pages_total`` counts every ``.md`` under a top-level directory the
    purge recognises as a page kind — the denominator ``scanned`` has to
    be read against. ``unrecognised`` names the top-level directories
    that hold markdown yet are neither a page kind nor a reserved
    ``_``/``.`` bucket: pages no purge can ever reach, and the signal
    that the path contract has grown a kind this handler does not know
    (issue #622).
    """

    pages_total: int = 0
    unrecognised: set[str] = field(default_factory=set)

    def note(self, top: str) -> bool:
        """Record one markdown file by its top-level directory.

        Returns whether the file sits under a known page kind, so the
        caller can decide in the same pass whether to evaluate it — one
        walk of the tree, not two.
        """
        if top in PAGE_DIRS:
            self.pages_total += 1
            return True
        if not top.startswith((".", "_")):
            self.unrecognised.add(top)
        return False


@dataclass(frozen=True, kw_only=True)
class RejectAxes:
    """Which reject axes this sweep runs, and at what thresholds.

    The five settings travel together on every page, so they are one
    value rather than five parameters (coding-standards.md §4.4).
    """

    check_stub: bool
    check_shallow: bool
    check_classifier: bool
    stub_threshold: float
    shallow_threshold: int


def parse_tags(raw: Any) -> list[str]:
    """Extract a list of tag strings from frontmatter value (list or CSV)."""
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if not isinstance(raw, str):
        return []
    stripped = raw.strip().strip("[]")
    return [t.strip().strip("'\"") for t in stripped.split(",") if t.strip()]


def evaluate_page(
    md_path: Path, axes: RejectAxes
) -> tuple[str | None, list[str], str | None, float]:
    """Evaluate a page against the configured reject axes.

    Three axes, checked in order — stub first (cheapest, unambiguous),
    shallow next (auto-gen file dumps), classifier last (most expensive).

      * ``stub`` — body is majority placeholder markers.
      * ``shallow`` — body has too few prose chars to be an explanation.
      * ``classifier_reject`` — classifier no longer admits the content.
    """
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    r = parse_yaml_frontmatter(text)
    tags = parse_tags(r.meta.get("tags"))
    body = r.body or ""
    score = stub_score(body)

    if axes.check_stub and is_stub(body, threshold=axes.stub_threshold):
        return None, tags, "stub", score

    if axes.check_shallow and is_shallow(body, threshold=axes.shallow_threshold):
        return None, tags, "shallow", score

    if axes.check_classifier:
        lines = body.strip().splitlines()
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        content = "\n".join(lines).strip() or str(r.meta.get("title", ""))
        result = classify_memory(content, tags)
        kind = result.kind if result is not None else None
        if kind is None:
            return None, tags, "classifier_reject", score
        return kind, tags, None, score

    # No axis fired — keep the page (use this for stat-only runs).
    return "_unchecked", tags, None, score


def candidate_pages(root: Path, target_dirs: set[str]) -> tuple[list[Path], Census]:
    """One walk: census the whole tree, return the pages in scope.

    The census is taken here, before the caller unlinks anything, so the
    total stays the one ``scanned`` is read against after an apply.
    """
    census = Census()
    in_scope: list[Path] = []
    for md in sorted(root.rglob("*.md")):
        parts = md.relative_to(root).parts
        if len(parts) < MIN_PAGE_PARTS:
            continue
        if not census.note(parts[0]):
            continue
        if parts[0] in target_dirs:
            in_scope.append(md)
    return in_scope, census


__all__ = [
    "MIN_PAGE_PARTS",
    "PAGE_DIRS",
    "Census",
    "RejectAxes",
    "candidate_pages",
    "evaluate_page",
    "parse_tags",
]
