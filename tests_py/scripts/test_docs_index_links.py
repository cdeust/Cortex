"""Every link in the task-based documentation index must resolve (issue #723).

``docs/README.md`` owns no facts: it routes a reader to the document that does.
A route that points at a renamed file or a reworded heading sends the reader
nowhere, and GitHub renders that silently. These tests resolve each relative
link to a tracked path and each ``#fragment`` to a heading slug of its target.

Slug rule: GitHub's heading anchors lowercase the text, drop every character
that is not a letter, digit, space, hyphen or underscore, turn each space into
a hyphen, and suffix repeats with ``-1``, ``-2``...
source: github/cmark-gfm, extensions' anchor generation as used by github.com
(https://github.com/github/cmark-gfm), observed on this repository's README
anchors linked from README.md (e.g. ``#green-software-engineering``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX = REPO_ROOT / "docs" / "README.md"

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def github_slug(heading: str) -> str:
    """The anchor GitHub generates for one heading's text."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def heading_slugs(markdown: str) -> set[str]:
    """Anchors of every heading outside fenced code, with repeat suffixes."""
    seen: dict[str, int] = {}
    slugs: set[str] = set()
    in_fence = False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        match = None if in_fence else _HEADING.match(line)
        if match is None:
            continue
        base = github_slug(match.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        slugs.add(base if count == 0 else f"{base}-{count}")
    return slugs


def _relative_links() -> list[str]:
    links = _LINK.findall(INDEX.read_text(encoding="utf-8"))
    return [link for link in links if not re.match(r"^[a-z]+:", link)]


def test_the_index_routes_somewhere() -> None:
    """Guards the parametrised test below against passing on zero links."""
    assert len(_relative_links()) >= 10


@pytest.mark.parametrize("link", _relative_links())
def test_each_relative_link_resolves_to_a_file_and_heading(link: str) -> None:
    path_part, _, fragment = link.partition("#")
    target = (INDEX.parent / path_part).resolve() if path_part else INDEX
    assert target.exists(), f"docs/README.md links to missing {path_part!r}"
    assert REPO_ROOT in target.parents or target == REPO_ROOT
    if fragment:
        assert target.suffix == ".md", f"anchor on non-Markdown target {link!r}"
        slugs = heading_slugs(target.read_text(encoding="utf-8"))
        assert fragment in slugs, f"{link!r}: no heading with anchor #{fragment}"


@pytest.mark.parametrize(
    ("heading", "slug"),
    [
        ("Green software engineering", "green-software-engineering"),
        ("Tier 1 — Core Memory & Profiling", "tier-1--core-memory--profiling"),
        ("Memory Write Path (`remember`)", "memory-write-path-remember"),
        ("1. Is it hung or just slow?", "1-is-it-hung-or-just-slow"),
    ],
)
def test_slug_rule_matches_github_anchors(heading: str, slug: str) -> None:
    assert github_slug(heading) == slug


def test_repeated_headings_get_numbered_anchors() -> None:
    slugs = heading_slugs("# A\n## A\n```\n# A\n```\n### A\n")
    assert slugs == {"a", "a-1", "a-2"}
