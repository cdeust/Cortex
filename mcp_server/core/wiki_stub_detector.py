"""Stub detector for wiki pages — pure logic, no I/O.

A "stub page" is one whose body is mostly placeholder markers:
``_(to be filled)_``, ``_To be written._``, ``_(none identified)_``,
``(TBD)``. These are typically produced by:

  * The groomer adding canonical template sections with placeholder text
    when the source memory had no content for that section.
  * Template-based synthesizers (``synth_model: template_v1`` etc.) that
    expanded a thin memory into a multi-section skeleton.

Stub pages are noise. A reader opening the wiki sees them and concludes
the documentation is untrustworthy. They must be purged, and the
producers that emit them must be changed to leave sections short rather
than padded with placeholders.

This module defines:

  * ``PLACEHOLDER_PATTERNS`` — the recognised marker variants.
  * ``stub_score(body)`` — fraction of body content lines that are
    placeholder-only. Returns 0.0 for a substantive page, approaches 1.0
    as the body becomes pure placeholders.
  * ``is_stub(body, threshold=0.5)`` — boolean shorthand: True iff
    ``stub_score`` exceeds the threshold.

Source for the threshold: hand-inspected the 14 stub Lessons and 50
stub Specs from the 2026-05-18 audit. Pages with ``stub_score >= 0.5``
were 100% noise; pages with score in (0.0, 0.5) were mixed — some real
content, some placeholders. Default 0.5 is the conservative bar that
removes the obvious noise without touching mixed pages.
"""

from __future__ import annotations

import re
from typing import Final

# ── Recognised placeholder markers ────────────────────────────────────


PLACEHOLDER_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # Groomer placeholders.
    re.compile(r"^_\(none identified\)_\s*$"),
    re.compile(r"^_\(to be filled\)_\s*$"),
    re.compile(r"^_To be written\._\s*$"),
    re.compile(r"^_TBD_\s*$", re.IGNORECASE),
    # Looser variants (no surrounding underscores).
    re.compile(r"^\(none identified\)\s*$"),
    re.compile(r"^\(to be filled\)\s*$"),
    re.compile(r"^To be written\.?\s*$"),
    re.compile(r"^TBD\s*$"),
    # Boilerplate "(to be filled)" embedded in headings ("# Foo (to be filled)").
    re.compile(r".*\(to be filled\)\s*$", re.IGNORECASE),
)


_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_BLANK_RE = re.compile(r"^\s*$")


def _is_placeholder_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    for pat in PLACEHOLDER_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def _is_content_line(line: str) -> bool:
    """A content line is one that contributes meaning — not a heading,
    not blank, not a horizontal rule, not a fence marker.

    Headings are excluded because they belong to the template structure,
    not the authored prose; a page consisting of headings + placeholders
    is a stub.
    """
    if _BLANK_RE.match(line):
        return False
    stripped = line.strip()
    if _HEADING_RE.match(stripped):
        return False
    if stripped in ("---", "***", "```"):
        return False
    if stripped.startswith("```"):
        return False
    return True


def stub_score(body: str) -> float:
    """Fraction of content lines that are placeholder markers.

    Returns 0.0 when the body has no placeholder content (or no content
    at all — see ``is_stub`` for the empty-body case). 1.0 when every
    non-heading non-blank line is a placeholder marker.
    """
    if not body:
        return 0.0
    content_lines = [ln for ln in body.splitlines() if _is_content_line(ln)]
    if not content_lines:
        return 0.0
    placeholder_count = sum(1 for ln in content_lines if _is_placeholder_line(ln))
    return placeholder_count / len(content_lines)


# Default threshold — see module docstring for calibration.
DEFAULT_STUB_THRESHOLD: Final[float] = 0.5


def is_stub(body: str, threshold: float = DEFAULT_STUB_THRESHOLD) -> bool:
    """True iff the body's stub score meets or exceeds ``threshold``.

    Also returns True for a body that contains *any* content lines and
    *all* of them are placeholder markers, regardless of threshold — a
    page whose entire authored content is placeholders is unambiguously
    a stub.
    """
    score = stub_score(body)
    if score >= 1.0:
        return True
    return score >= threshold


def placeholder_count(body: str) -> int:
    """Total placeholder marker lines in the body. Useful for reporting
    aggregate noise across the wiki without re-deriving the score.
    """
    if not body:
        return 0
    return sum(1 for ln in body.splitlines() if _is_placeholder_line(ln))


# ── Shallow-content detector ──────────────────────────────────────────
#
# A page is *shallow* when its body has very little actual prose — it's
# mostly headings, lists, metadata key-value lines, and code fences.
# These pages occur en masse from auto-generators (``codebase_analyze``,
# template synthesizers) that produced one file-doc per source file
# with body shape:
#
#     # File: foo.py  # noqa: ERA001 -- stub-shape doc, not code
#     Language: python  # noqa: ERA001 -- stub-shape doc, not code
#     Purpose: foo.py — one-liner.
#     ## Imports
#     - bar
#     - baz
#     N lines
#
# Such pages aren't *wrong*, but they aren't *explanations* either.
# They take space in the tree, mislead readers into thinking the
# project is documented when it isn't, and the curator can't tell
# them apart from real reference pages without this signal.

_KV_METADATA_LINE = re.compile(
    r"^[A-Z][a-zA-Z _\-]{0,30}:\s*\S",  # "Language: python", "Updated: 2026-…"
)
_LIST_BULLET = re.compile(r"^(?:[-*+]\s|\d+\.\s)")


def prose_char_count(body: str) -> int:
    """Count characters of actual prose in ``body``.

    Excludes: headings (lines starting with ``#``), list items, code
    fences and their contents, blank lines, and key-value metadata
    lines. What remains is what a reader would call "the explanation".
    """
    if not body:
        return 0
    total = 0
    in_fence = False
    for ln in body.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if s.startswith("#"):
            continue
        if _LIST_BULLET.match(s):
            continue
        if _KV_METADATA_LINE.match(s):
            continue
        total += len(s)
    return total


# Default threshold below which a page is considered shallow. Calibrated
# on the 2026-05-18 audit: 96% of surviving auto-gen pages had under
# 500 chars of real prose; hand-authored pages typically have 2 000+.
DEFAULT_SHALLOW_THRESHOLD: Final[int] = 500


def is_shallow(body: str, threshold: int = DEFAULT_SHALLOW_THRESHOLD) -> bool:
    """True when the body has fewer than ``threshold`` prose chars.

    A shallow page isn't a stub (it doesn't have placeholder markers),
    isn't a classifier-reject (the content is on-topic), but it isn't
    an *explanation* either — it's metadata dressed up as a page.
    """
    return prose_char_count(body) < threshold
