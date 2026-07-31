"""Canonical truth-readers for scripts/check_doc_claims.py.

Extracted (issue #293, Extract Function/Move Function) so check_doc_claims.py
stays under the repo's 300-line file cap (CLAUDE.md, Code Style) — it had
already crossed it (420 lines) before this change added the floor-check
machinery check_doc_claims.py needed.

Each function here answers ONE question: "what does the repository itself
say tool/reference/mechanism/version counts are?" They take `read_fn` as an
explicit parameter (constructor injection, coding-standards.md §5) rather
than importing a module-level `read` — check_doc_claims.py keeps a thin
wrapper of the same name that passes ITS OWN (test-patchable) `read`
through, so `gate.read = fake` in tests_py/scripts/test_check_doc_claims.py
still reaches these bodies exactly as it did before the split.

TRY003 (issue #239): every ``raise ClaimError(...)`` below names a
distinct, one-off doc-claim mismatch (a specific pattern absent, or two
specific counts disagreeing) — never reused (§3.3). Marked with a bare
`# noqa: TRY003` at each site rather than repeating this paragraph.
"""

from __future__ import annotations

import re
from collections.abc import Callable

ReadFn = Callable[[str], str]

# str.split(marker, 1) yields exactly (before, after) when the marker is
# present — source: structural, not measured.
_MARKER_SPLIT_PARTS = 2


class ClaimError(Exception):
    """A canonical source could not be read — the gate cannot run blind."""


def canonical_tool_counts(read_fn: ReadFn) -> tuple[int, int]:
    """(standalone, total) from the mcp-tools.md header, cross-checked.

    The header sentence is the single place the catalogue states the counts;
    the pinned test name in tests_py/test_main.py carries the registry-derived
    standalone number, so the two disagreeing means the catalogue drifted from
    the server itself.
    """
    header = read_fn("docs/mcp-tools.md")
    match = re.search(
        r"(\d+)\s+standalone tools register unconditionally;"
        r"\s*(\d+)\s+more[^(]*\((\d+)\s+total",
        header,
    )
    if not match:
        raise ClaimError("docs/mcp-tools.md: standalone/total tool sentence not found")  # noqa: TRY003
    standalone, extra, total = (int(g) for g in match.groups())
    if standalone + extra != total:
        raise ClaimError(f"docs/mcp-tools.md: {standalone} + {extra} != {total}")  # noqa: TRY003

    pinned = re.search(
        r"test_standalone_baseline_is_(\d+)_tools", read_fn("tests_py/test_main.py")
    )
    if not pinned:
        raise ClaimError("tests_py/test_main.py: pinned tool-count test not found")  # noqa: TRY003
    if int(pinned.group(1)) != standalone:
        raise ClaimError(  # noqa: TRY003
            f"docs/mcp-tools.md says {standalone} standalone tools, but the pinned "
            f"registry test says {pinned.group(1)}"
        )
    return standalone, total


def canonical_reference_count(read_fn: ReadFn) -> int:
    """Entries counted in the bibliography, which declares itself canonical."""
    body = read_fn("docs/papers/bibliography.md").split("## References", 1)
    if len(body) != _MARKER_SPLIT_PARTS:
        raise ClaimError(  # noqa: TRY003
            "docs/papers/bibliography.md: '## References' section not found"
        )
    entries = [
        line
        for line in body[1].splitlines()
        if line.strip() and not line.startswith(("#", "---"))
    ]
    if not entries:
        raise ClaimError("docs/papers/bibliography.md: no reference entries found")  # noqa: TRY003
    return len(entries)


def canonical_mechanism_count(read_fn: ReadFn) -> int:
    """The mechanism count declared in the bibliography header.

    Mechanisms are not machine-countable (they are implementations spread over
    core modules), so one file declares the number and every other file must
    agree with it. Changing the count is a one-line edit here plus whatever the
    gate then reports as stale.
    """
    pattern = re.compile(
        r"(\d+)\s+(?:neuroscience[- ]grounded|neuroscience|biological|brain)?"
        r"\s*mechanisms\b"
    )
    match = pattern.search(read_fn("docs/papers/bibliography.md"))
    if not match:
        raise ClaimError("docs/papers/bibliography.md: no mechanism count declared")  # noqa: TRY003
    return int(match.group(1))


def canonical_version(read_fn: ReadFn) -> str:
    match = re.search(
        r'^version\s*=\s*"([^"]+)"', read_fn("pyproject.toml"), re.MULTILINE
    )
    if not match:
        raise ClaimError("pyproject.toml: [project].version not found")  # noqa: TRY003
    return match.group(1)
