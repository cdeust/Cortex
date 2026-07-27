"""Tests for scripts/check_doc_claims.py — the doc-claim gate.

The gate's own failure mode is silence: a regex that stops matching, or a
canonical source it cannot read, would let every claim drift unnoticed. These
tests pin both the detection (a wrong number fails) and the vacuity guard (no
claim at all fails), plus the history exemption that keeps release notes from
being rewritten.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_doc_claims",
    Path(__file__).resolve().parents[2] / "scripts" / "check_doc_claims.py",
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


CATALOGUE = (
    "52 standalone tools register unconditionally; 3 more register only when an\n"
    "upstream MCP server is configured (55 total with both present).\n"
)
PINNED_TEST = "    def test_standalone_baseline_is_52_tools(self):\n"
BIBLIOGRAPHY = (
    "The 97-reference bibliography behind Cortex's 36 neuroscience-grounded\n"
    "mechanisms.\n\n## References\n\nAuthor, A. (2001). One.\n\nAuthor, B. (2002). Two.\n"
)


class _FakeRepo:
    """Minimal stand-in for the repository files the gate reads."""

    def __init__(self, **files: str):
        self.files = files

    def read(self, relative_path: str) -> str:
        return self.files[relative_path]


class CanonicalSourceTests(unittest.TestCase):
    def setUp(self):
        self._real_read = gate.read

    def tearDown(self):
        gate.read = self._real_read

    def _install(self, **files: str):
        gate.read = _FakeRepo(**files).read

    def test_tool_counts_come_from_the_catalogue(self):
        self._install(
            **{"docs/mcp-tools.md": CATALOGUE, "tests_py/test_main.py": PINNED_TEST}
        )
        self.assertEqual(gate.canonical_tool_counts(), (52, 55))

    def test_catalogue_drifting_from_the_pinned_registry_test_is_an_error(self):
        drifted = CATALOGUE.replace("52 standalone", "50 standalone").replace(
            "(55 total", "(53 total"
        )
        self._install(
            **{"docs/mcp-tools.md": drifted, "tests_py/test_main.py": PINNED_TEST}
        )
        with self.assertRaises(gate.ClaimError) as caught:
            gate.canonical_tool_counts()
        self.assertIn("pinned registry test", str(caught.exception))

    def test_inconsistent_arithmetic_in_the_catalogue_is_an_error(self):
        broken = CATALOGUE.replace("(55 total", "(56 total")
        self._install(
            **{"docs/mcp-tools.md": broken, "tests_py/test_main.py": PINNED_TEST}
        )
        with self.assertRaises(gate.ClaimError):
            gate.canonical_tool_counts()

    def test_reference_count_is_the_number_of_entries_not_the_advertised_number(self):
        self._install(**{"docs/papers/bibliography.md": BIBLIOGRAPHY})
        self.assertEqual(gate.canonical_reference_count(), 2)

    def test_bibliography_without_a_references_section_is_an_error(self):
        self._install(**{"docs/papers/bibliography.md": "# Bibliography\n"})
        with self.assertRaises(gate.ClaimError):
            gate.canonical_reference_count()

    def test_mechanism_count_is_read_from_the_bibliography_header(self):
        self._install(**{"docs/papers/bibliography.md": BIBLIOGRAPHY})
        self.assertEqual(gate.canonical_mechanism_count(), 36)

    def test_undeclared_mechanism_count_is_an_error(self):
        self._install(
            **{"docs/papers/bibliography.md": "# B\n\n## References\n\nA. (1)\n"}
        )
        with self.assertRaises(gate.ClaimError):
            gate.canonical_mechanism_count()

    def test_version_comes_from_pyproject(self):
        self._install(
            **{"pyproject.toml": '[project]\nname = "x"\nversion = "4.16.0"\n'}
        )
        self.assertEqual(gate.canonical_version(), "4.16.0")


class ScanTests(unittest.TestCase):
    def setUp(self):
        self._real_read = gate.read
        self._real_files = gate.SCANNED_FILES

    def tearDown(self):
        gate.read = self._real_read
        gate.SCANNED_FILES = self._real_files

    def _install(self, text: str):
        gate.read = _FakeRepo(**{"DOC.md": text}).read
        gate.SCANNED_FILES = ("DOC.md",)

    def test_wrong_count_is_reported_with_file_and_line(self):
        self._install("intro\nExposes 50 memory tools today.\n")
        failures = gate.check_counts(gate.TOOL_CLAIM, 52, "tools")
        self.assertEqual(len(failures), 1)
        self.assertIn("DOC.md:2", failures[0])
        self.assertIn("advertises 50 tools", failures[0])

    def test_matching_count_produces_no_failure(self):
        self._install("Exposes 52 memory tools today.\n")
        self.assertEqual(gate.check_counts(gate.TOOL_CLAIM, 52, "tools"), [])

    def test_release_history_lines_are_exempt(self):
        self._install(
            "Exposes 52 memory tools today.\n"
            "**v4.13.0 — grooming.** **49 memory tools** (52 with upstream).\n"
        )
        self.assertEqual(gate.check_counts(gate.TOOL_CLAIM, 52, "tools"), [])

    def test_a_pattern_that_matches_nothing_fails_instead_of_passing_vacuously(self):
        self._install("No numbers here.\n")
        failures = gate.check_counts(gate.TOOL_CLAIM, 52, "tools")
        self.assertEqual(len(failures), 1)
        self.assertIn("vacuously", failures[0])


class VersionTests(unittest.TestCase):
    def setUp(self):
        self._real_read = gate.read

    def tearDown(self):
        gate.read = self._real_read

    def _install(self, manifest: str, badge: str):
        gate.read = _FakeRepo(
            **{
                "manifest.json": '{"version": "%s"}' % manifest,
                "server.json": '{"version": "4.16.0"}',
                "package.json": '{"version": "4.16.0"}',
                "README.md": f"badge/version-{badge}-brightgreen.svg",
            }
        ).read

    def test_manifest_and_badge_must_match_pyproject(self):
        self._install(manifest="4.16.0", badge="4.16.0")
        self.assertEqual(gate.check_versions("4.16.0"), [])

    def test_stale_manifest_version_is_reported(self):
        self._install(manifest="4.15.0", badge="4.16.0")
        failures = gate.check_versions("4.16.0")
        self.assertEqual(len(failures), 1)
        self.assertIn("manifest.json", failures[0])

    def test_stale_readme_badge_is_reported(self):
        self._install(manifest="4.16.0", badge="4.15.0")
        failures = gate.check_versions("4.16.0")
        self.assertEqual(len(failures), 1)
        self.assertIn("version badge 4.15.0", failures[0])


class RepositoryTests(unittest.TestCase):
    """The gate must pass on the tree it ships with — this is the gate itself."""

    def test_committed_docs_agree_with_the_repository(self):
        self.assertEqual(gate.collect_failures(test_count=None), [])


if __name__ == "__main__":
    unittest.main()
