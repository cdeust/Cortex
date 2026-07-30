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
test count           ``assets/badge-tests.svg`` alone (issue #287) — the
                     one artifact that still states an absolute figure. No
                     prose file (nor ``.bestpractices.json``) states this
                     count any more: a PR that adds tests would otherwise
                     have to hand-edit six files to the same new number,
                     and any two such PRs conflict on every one of them BY
                     CONSTRUCTION. The badge is also not an exact fact —
                     it is checked as a monotone FLOOR (``committed <=
                     live``), because the true count is a property of the
                     post-merge tree that no single branch can compute in
                     advance; only an OVER-claim is reported. See
                     ``doc_claim_structural.check_badge_floor``.
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

Split across scripts/doc_claim_sources.py (canonical readers),
scripts/doc_claim_scan.py (claim scanning/comparison) and
scripts/doc_claim_structural.py (badge + structural-integrity checks) —
issue #287, Extract Function/Move Function — to stay under the repo's
300-line file cap (CLAUDE.md, Code Style); this module is the thin
orchestrator each of those forwards through, and the only place ``read``/
``SCANNED_FILES`` are defined (tests patch them here; see each sibling
module's docstring for why they take these as parameters instead).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Sibling modules, path-imported for the same reason generate_repo_badges.py
# does it: resolves identically whether this runs as a script or is loaded
# via importlib.util.spec_from_file_location from a test.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import doc_claim_scan  # noqa: E402
import doc_claim_sources  # noqa: E402
import doc_claim_structural  # noqa: E402
from doc_claim_sources import ClaimError  # noqa: E402  (re-export)

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

TOOL_CLAIM = re.compile(r"(\d+)\s+(?:memory|standalone|MCP)\s+tools\b")
TOOL_TOTAL_CLAIM = re.compile(r"\((\d+)\s+(?:total\s+)?with\b[^)]*\)")
REFERENCE_CLAIM = re.compile(r"(\d+)[-\s]reference\b")
MECHANISM_CLAIM = re.compile(
    r"(\d+)\s+(?:neuroscience[- ]grounded|neuroscience|biological|brain)?"
    r"\s*mechanisms\b"
)
# Both the "N tests" and the "N-test suite" phrasings state the count. No
# scanned file states this claim in prose any more (issue #287 — see the
# module docstring's "test count" row); the pattern stays defined because
# it is still the generic worked example scan_claims/check_counts's own
# tests exercise, and tests_py/scripts/test_check_doc_claims.py asserts its
# absence from the real tree as a standing regression guard (a re-added
# hardcoded prose count would fail
# RepositoryTests.test_no_prose_file_states_the_suite_size).
TEST_CLAIM = re.compile(r"(\d+)(?:\s+tests|-test suite)\b")


def read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def canonical_tool_counts() -> tuple[int, int]:
    return doc_claim_sources.canonical_tool_counts(read)


def canonical_reference_count() -> int:
    return doc_claim_sources.canonical_reference_count(read)


def canonical_mechanism_count() -> int:
    return doc_claim_sources.canonical_mechanism_count(read)


def canonical_version() -> str:
    return doc_claim_sources.canonical_version(read)


def exemption_registry() -> list[tuple[str, int, str]]:
    """Every declared not-a-claim marker: (file, line, the family it exempts)."""
    return doc_claim_scan.exemption_registry(SCANNED_FILES, read)


def scan_claims(pattern: re.Pattern[str], label: str) -> list[tuple[str, int, int]]:
    """Every (file, line number, claimed value) that claims `label`."""
    return doc_claim_scan.scan_claims(pattern, label, SCANNED_FILES, read)


def check_counts(pattern: re.Pattern[str], expected: int, label: str) -> list[str]:
    """Report claims that disagree — and the absence of any claim at all."""
    return doc_claim_scan.check_counts(pattern, expected, label, SCANNED_FILES, read)


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
    failures += doc_claim_structural.check_badge(
        "assets/badge-version.svg",
        doc_claim_structural.VERSION_BADGE,
        expected,
        "version",
        read,
    )
    return failures


def check_no_hotlinked_badges() -> list[str]:
    """The README's repo-derived badges stay self-hosted."""
    return doc_claim_structural.check_no_hotlinked_badges(read)


def check_no_conflict_markers() -> list[str]:
    """No scanned file states both sides of a claim at once."""
    return doc_claim_structural.check_no_conflict_markers(SCANNED_FILES, read)


def check_scanned_json_parses() -> list[str]:
    """Every scanned .json file is still machine-readable."""
    return doc_claim_structural.check_scanned_json_parses(SCANNED_FILES, read)


def collect_failures(test_count: int | None) -> list[str]:
    standalone, total = canonical_tool_counts()
    failures = check_counts(TOOL_CLAIM, standalone, "tools")
    failures += check_counts(TOOL_TOTAL_CLAIM, total, "tools with integrations")
    failures += check_counts(REFERENCE_CLAIM, canonical_reference_count(), "references")
    failures += check_counts(MECHANISM_CLAIM, canonical_mechanism_count(), "mechanisms")
    failures += check_versions(canonical_version())
    failures += check_no_hotlinked_badges()
    failures += check_no_conflict_markers()
    failures += check_scanned_json_parses()
    if test_count is not None:
        # The tests badge is the ONLY test-count claim left (issue #287);
        # see check_badge_floor's docstring for why it is a floor, not an
        # exact match.
        failures += doc_claim_structural.check_badge_floor(
            "assets/badge-tests.svg",
            doc_claim_structural.TESTS_BADGE,
            test_count,
            "tests",
            read,
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
