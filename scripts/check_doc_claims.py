"""Doc-claim gate: the numbers the docs advertise must match the repository.

This gate closes that at the point where the drift is introduced (every push
and pull request), not at release time. It compares every advertised count
against the one place that owns it:

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

source: ADR-0713"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# source: ADR-0713
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import doc_claim_scan  # noqa: E402
import doc_claim_sources  # noqa: E402
import doc_claim_structural  # noqa: E402
from doc_claim_sources import ClaimError  # noqa: E402  (re-export)

# source: ADR-0713
SCANNED_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CLAUDE.md",
    # source: ADR-0713
    "docs/agent-guidance.md",
    "GOVERNANCE.md",
    "manifest.json",
    "docs/ROADMAP.md",
    "docs/ASSURANCE-CASE.md",
    "docs/mcp-tools.md",
    "docs/module-inventory.md",
    "docs/api-reference.md",
    "docs/papers/bibliography.md",
    # source: ADR-0713
    ".bestpractices.json",
    # source: ADR-0713
    "server.json",
    # The Codex package's own shipped docs and the two repository docs that
    # describe it. They carry no counted claim today; they are scanned so a
    # future digit-based one cannot drift, which is the gap that let "9
    # lifecycle hooks" sit next to "eleven" in one README (PR #620).
    "plugins/hypermnesia-mcp-codex/README.md",
    "plugins/hypermnesia-mcp-codex/SECURITY.md",
    # The manifest a Codex marketplace shows to every installer: its
    # description and longDescription both state the hook count.
    "plugins/hypermnesia-mcp-codex/.codex-plugin/plugin.json",
    "docs/codex-plugin.md",
    "docs/shared-host-memory.md",
)

TOOL_CLAIM = re.compile(r"(\d+)\s+(?:memory|standalone|MCP)\s+tools\b")
TOOL_TOTAL_CLAIM = re.compile(r"\((\d+)\s+(?:total\s+)?with\b[^)]*\)")
REFERENCE_CLAIM = re.compile(r"(\d+)[-\s]reference\b")
# source: ADR-0713
MECHANISM_CLAIM = re.compile(
    r"(\d+)\s+(?:cited\s+)?(?:neuroscience[- ]grounded|neuroscience|biological|brain)?"
    r"\s*mechanisms\b"
)
# source: ADR-0713
TEST_CLAIM = re.compile(r"(\d+)(?:\s+tests|-test suite)\b")
# The docs said "9 lifecycle hooks" through the two that #605 added, and the
# Codex parity work (PR #620) then put "eleven" in the same README, so the
# file contradicted itself. Counted from the entry-point allowlist, not
# declared, because that allowlist is what both manifests wire.
HOOK_CLAIM = re.compile(r"(\d+)\s+lifecycle\s+hooks\b")
# The pinned test name carries the standalone count inside an identifier,
# where no space precedes the digits, so TOOL_CLAIM never saw it and it
# sat stale at 52 across two count moves.
# source: the decision recorded as ADR number 1077
PINNED_TEST_NAME_CLAIM = re.compile(r"test_standalone_baseline_is_(\d+)_tools")


def read(relative_path: str) -> str:
    # encoding="utf-8" is pinned explicitly, never the platform default:
    # source: ADR-0713
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def canonical_tool_counts() -> tuple[int, int]:
    return doc_claim_sources.canonical_tool_counts(read)


def canonical_reference_count() -> int:
    return doc_claim_sources.canonical_reference_count(read)


def canonical_mechanism_count() -> int:
    return doc_claim_sources.canonical_mechanism_count(read)


def canonical_hook_count() -> int:
    return doc_claim_sources.canonical_hook_count(read)


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
    failures += check_counts(
        PINNED_TEST_NAME_CLAIM, standalone, "tools in the pinned test name"
    )
    failures += doc_claim_structural.check_marketplace_tool_counts(
        read, standalone, total
    )
    failures += check_counts(REFERENCE_CLAIM, canonical_reference_count(), "references")
    failures += check_counts(MECHANISM_CLAIM, canonical_mechanism_count(), "mechanisms")
    failures += check_counts(HOOK_CLAIM, canonical_hook_count(), "lifecycle hooks")
    failures += check_no_hotlinked_badges()
    failures += check_no_conflict_markers()
    failures += check_scanned_json_parses()
    if test_count is not None:
        # source: ADR-0713
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
        # source: ADR-0713
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
