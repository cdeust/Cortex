"""Doc-claim gate: the numbers the docs advertise must match the repository.

Cortex advertises counts in prose — tools, references, mechanisms, version,
tests. Each one is a claim a reader can check, and each one drifts silently:
between 2026-07-12 and 2026-07-27 the tool count moved from 49 to 52 while
README, CONTRIBUTING and the MCPB manifest still said 50, 43 and 49, and
CONTRIBUTING advertised a ``mypy --strict`` gate the project has never run.
Nothing failed, because nothing checked.

This gate closes that at the point where the drift is introduced (every push
and pull request), not at release time. It compares every advertised count
against the one place that owns it:

===================  =====================================================
Claim                Owner
===================  =====================================================
tool counts          ``docs/mcp-tools.md`` header, itself pinned to the live
                     registry by ``tests_py/test_main.py::
                     test_standalone_baseline_is_52_tools``
reference count      entries counted in ``docs/papers/bibliography.md``
mechanism count      the count declared in that bibliography's header
version              ``[project].version`` in ``pyproject.toml``
test count           ``--test-count``, from a live ``pytest --collect-only``
===================  =====================================================

Release history is exempt: a line describing v4.13.0 may legitimately say
"49 memory tools". Lines carrying a ``**vX.Y.Z`` marker, and files that are
history by nature (CHANGELOG, docs/release-notes/), are skipped.

A line may also state a number that counts something *other* than the
advertised total, in a wording the claim patterns cannot tell apart ("12
tests skipped locally"). Such a line declares
``[not-a-count-claim: <label>]`` and is skipped for that one family only —
see ``NOT_A_CLAIM``. The declared set is a registry: it is printed on every
successful run and pinned by a test naming each member, so an exemption is
added deliberately or not at all.

Usage::

    python scripts/check_doc_claims.py                 # static claims
    python scripts/check_doc_claims.py --test-count 5571
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files whose numbers describe the present. Release history lives elsewhere
# (CHANGELOG.md, docs/release-notes/) and is deliberately not scanned.
SCANNED_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CLAUDE.md",
    "GOVERNANCE.md",
    "manifest.json",
    "docs/ROADMAP.md",
    "docs/ASSURANCE-CASE.md",
    "docs/mcp-tools.md",
    "docs/module-inventory.md",
    "docs/api-reference.md",
    "docs/papers/bibliography.md",
    # The OpenSSF Best Practices answers are claims about the present too: they
    # are transcribed into the questionnaire, so a stale number here is
    # published to the badge. Three of its test counts had drifted two
    # corrections behind the repository before it was scanned (2026-07-27).
    ".bestpractices.json",
)

# A line introducing a past release states that release's numbers.
HISTORY_MARKER = re.compile(r"\*\*v\d+\.\d+\.\d+")

# A line whose number counts something else declares which family it is not a
# claim for. Rewording the prose to dodge a pattern would hide a true, measured
# number to keep the gate quiet; declaring it keeps the number and puts the
# exemption on the record, at the one site that knows why it is not a claim.
# The label must match a claim family exactly — an unrecognised or misspelled
# label exempts nothing, so the marker fails closed.
NOT_A_CLAIM = re.compile(r"\[not-a-count-claim: ([a-z][a-z ]*)\]")

TOOL_CLAIM = re.compile(r"(\d+)\s+(?:memory|standalone|MCP)\s+tools\b")
TOOL_TOTAL_CLAIM = re.compile(r"\((\d+)\s+(?:total\s+)?with\b[^)]*\)")
REFERENCE_CLAIM = re.compile(r"(\d+)[-\s]reference\b")
MECHANISM_CLAIM = re.compile(
    r"(\d+)\s+(?:neuroscience[- ]grounded|neuroscience|biological|brain)?"
    r"\s*mechanisms\b"
)
# Both the "N tests" and the "N-test suite" phrasings state the count; matching
# only the first let a stale number sit unread in .bestpractices.json.
TEST_CLAIM = re.compile(r"(\d+)(?:\s+tests|-test suite)\b")
VERSION_BADGE = re.compile(r"badge/version-(\d+\.\d+\.\d+)")

# source: structural — str.split(marker, 1) yields exactly (before, after)
# when the marker is present
_MARKER_SPLIT_PARTS = 2


class ClaimError(Exception):
    """A canonical source could not be read — the gate cannot run blind."""


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def canonical_tool_counts() -> tuple[int, int]:
    """(standalone, total) from the mcp-tools.md header, cross-checked.

    The header sentence is the single place the catalogue states the counts;
    the pinned test name in tests_py/test_main.py carries the registry-derived
    standalone number, so the two disagreeing means the catalogue drifted from
    the server itself.
    """
    header = read("docs/mcp-tools.md")
    match = re.search(
        r"(\d+)\s+standalone tools register unconditionally;"
        r"\s*(\d+)\s+more[^(]*\((\d+)\s+total",
        header,
    )
    if not match:
        raise ClaimError("docs/mcp-tools.md: standalone/total tool sentence not found")
    standalone, extra, total = (int(g) for g in match.groups())
    if standalone + extra != total:
        raise ClaimError(f"docs/mcp-tools.md: {standalone} + {extra} != {total}")

    pinned = re.search(
        r"test_standalone_baseline_is_(\d+)_tools", read("tests_py/test_main.py")
    )
    if not pinned:
        raise ClaimError("tests_py/test_main.py: pinned tool-count test not found")
    if int(pinned.group(1)) != standalone:
        raise ClaimError(
            f"docs/mcp-tools.md says {standalone} standalone tools, but the pinned "
            f"registry test says {pinned.group(1)}"
        )
    return standalone, total


def canonical_reference_count() -> int:
    """Entries counted in the bibliography, which declares itself canonical."""
    body = read("docs/papers/bibliography.md").split("## References", 1)
    if len(body) != _MARKER_SPLIT_PARTS:
        raise ClaimError(
            "docs/papers/bibliography.md: '## References' section not found"
        )
    entries = [
        line
        for line in body[1].splitlines()
        if line.strip() and not line.startswith(("#", "---"))
    ]
    if not entries:
        raise ClaimError("docs/papers/bibliography.md: no reference entries found")
    return len(entries)


def canonical_mechanism_count() -> int:
    """The mechanism count declared in the bibliography header.

    Mechanisms are not machine-countable (they are implementations spread over
    core modules), so one file declares the number and every other file must
    agree with it. Changing the count is a one-line edit here plus whatever the
    gate then reports as stale.
    """
    match = MECHANISM_CLAIM.search(read("docs/papers/bibliography.md"))
    if not match:
        raise ClaimError("docs/papers/bibliography.md: no mechanism count declared")
    return int(match.group(1))


def canonical_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', read("pyproject.toml"), re.MULTILINE)
    if not match:
        raise ClaimError("pyproject.toml: [project].version not found")
    return match.group(1)


def scannable_lines() -> Iterator[tuple[str, int, str]]:
    """Every (file, line number, text) that describes the present."""
    for relative_path in SCANNED_FILES:
        for number, line in enumerate(read(relative_path).splitlines(), start=1):
            if not HISTORY_MARKER.search(line):
                yield relative_path, number, line


def exemption_registry() -> list[tuple[str, int, str]]:
    """Every declared not-a-claim marker: (file, line, the family it exempts)."""
    return [
        (path, number, match.group(1))
        for path, number, line in scannable_lines()
        for match in NOT_A_CLAIM.finditer(line)
    ]


def scan_claims(pattern: re.Pattern[str], label: str) -> list[tuple[str, int, int]]:
    """Every (file, line number, claimed value) that claims `label`.

    A line declaring ``[not-a-count-claim: <label>]`` states that its number
    counts something else; it is skipped for that family only, so the same
    line still has to answer to every other one.
    """
    return [
        (path, number, int(match.group(1)))
        for path, number, line in scannable_lines()
        if label not in {m.group(1) for m in NOT_A_CLAIM.finditer(line)}
        for match in pattern.finditer(line)
    ]


def check_counts(pattern: re.Pattern[str], expected: int, label: str) -> list[str]:
    """Report claims that disagree — and the absence of any claim at all.

    A pattern that matches nothing would pass silently forever, which is how a
    gate becomes decorative: the vacuity guard makes a reworded (or deleted)
    claim a build failure rather than an unnoticed loss of coverage.
    """
    claims = scan_claims(pattern, label)
    if not claims:
        return [
            f"no {label} claim found in any scanned file — "
            f"the gate would pass vacuously"
        ]
    return [
        f"{path}:{line}: advertises {claimed} {label}, canonical is {expected}"
        for path, line, claimed in claims
        if claimed != expected
    ]


def check_versions(expected: str) -> list[str]:
    """The version in the packaging metadata, the badge and every manifest."""
    failures: list[str] = []
    for relative_path, key in (
        ("manifest.json", "version"),
        ("server.json", "version"),
        ("package.json", "version"),
    ):
        actual = json.loads(read(relative_path)).get(key)
        if actual != expected:
            failures.append(
                f"{relative_path}: version {actual!r}, pyproject says {expected!r}"
            )
    for match in VERSION_BADGE.finditer(read("README.md")):
        if match.group(1) != expected:
            failures.append(
                f"README.md: version badge {match.group(1)}, pyproject says {expected}"
            )
    return failures


def collect_failures(test_count: int | None) -> list[str]:
    standalone, total = canonical_tool_counts()
    failures = check_counts(TOOL_CLAIM, standalone, "tools")
    failures += check_counts(TOOL_TOTAL_CLAIM, total, "tools with integrations")
    failures += check_counts(REFERENCE_CLAIM, canonical_reference_count(), "references")
    failures += check_counts(MECHANISM_CLAIM, canonical_mechanism_count(), "mechanisms")
    failures += check_versions(canonical_version())
    if test_count is not None:
        failures += check_counts(TEST_CLAIM, test_count, "tests")
        badge = re.search(r"badge/tests-(\d+)_passing", read("README.md"))
        if badge and int(badge.group(1)) != test_count:
            failures.append(
                f"README.md: test badge says {badge.group(1)}, "
                f"the suite collects {test_count}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test-count",
        type=int,
        default=None,
        help="live test count (from `pytest --collect-only -q`); skipped when absent",
    )
    args = parser.parse_args()

    try:
        failures = collect_failures(args.test_count)
    except ClaimError as error:
        print(f"doc-claim gate could not run: {error}", file=sys.stderr)
        return 2

    if failures:
        print("Documentation claims disagree with the repository:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    exemptions = exemption_registry()
    print(f"doc claims OK ({len(exemptions)} declared not-a-claim exemption(s))")
    for path, line, label in exemptions:
        print(f"  {path}:{line}: exempt from the {label} claim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
