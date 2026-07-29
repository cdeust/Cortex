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

# The module name must be the dotted path mutmut derives from the file's
# location: it keys its mutant trampolines on "scripts.check_doc_claims.*",
# and a bare "check_doc_claims" makes every mutant look unreached, so the
# scoped mutation run stops early instead of scoring the suite.
_spec = importlib.util.spec_from_file_location(
    "scripts.check_doc_claims",
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
    "mechanisms.\n\n## References\n\nAuthor, A. (2001). One.\n\n"
    "Author, B. (2002). Two.\n"
)


class _FakeRepo:
    """Minimal stand-in for the repository files the gate reads."""

    def __init__(self, **files: str):
        self.files = files

    def read(self, relative_path: str) -> str:
        # FileNotFoundError, not KeyError: the real read() is a Path.read_text,
        # and the gate's missing-badge arm is written against what the real
        # one raises. A double that raised KeyError would let that arm pass
        # its tests while failing on the actual tree.
        try:
            return self.files[relative_path]
        except KeyError:
            raise FileNotFoundError(relative_path) from None


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

    def test_reference_entries_exclude_headings_and_separators(self):
        """A sectioned bibliography must not count its own furniture.

        The count feeds every "N-reference" claim in the docs, so a heading
        or a rule counted as an entry inflates the number the gate then
        enforces everywhere else.
        """
        self._install(
            **{
                "docs/papers/bibliography.md": (
                    "36 mechanisms.\n\n## References\n\n"
                    "### Neuroscience\n\n---\n\n"
                    "Author, A. (2001). One.\n\nAuthor, B. (2002). Two.\n"
                )
            }
        )
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

    def test_both_test_count_phrasings_state_the_same_claim(self):
        """ "N tests" and "N-test suite" are one claim in two wordings."""
        self._install("The suite has 5594 tests.\nCI runs a 5594-test suite.\n")
        self.assertEqual(gate.check_counts(gate.TEST_CLAIM, 5594, "tests"), [])

    def test_stale_hyphenated_test_count_is_reported(self):
        """The wording that went unread while it drifted two corrections behind."""
        self._install("The suite has 5594 tests.\nCI runs a 5571-test suite.\n")
        failures = gate.check_counts(gate.TEST_CLAIM, 5594, "tests")
        self.assertEqual(len(failures), 1)
        self.assertIn("DOC.md:2", failures[0])
        self.assertIn("advertises 5571 tests", failures[0])

    def test_a_count_of_test_files_is_not_a_suite_size_claim(self):
        """Widening the pattern must not turn every nearby number into a claim."""
        self._install("The suite has 5594 tests.\nThere are 3 test files.\n")
        self.assertEqual(gate.check_counts(gate.TEST_CLAIM, 5594, "tests"), [])

    def test_a_declared_exemption_is_not_a_claim_for_that_family(self):
        """A number that counts something else declares so, keeping its value."""
        self._install(
            "The suite has 5594 tests.\n"
            "12 tests skipped [not-a-count-claim: tests] locally\n"
        )
        self.assertEqual(gate.check_counts(gate.TEST_CLAIM, 5594, "tests"), [])

    def test_an_exemption_binds_only_the_family_it_names(self):
        """Unlike the history marker, it does not blind the whole line.

        The tools claim on the same line is still read and still reported —
        this is what makes the marker narrower than skipping the line.
        """
        self._install(
            "The suite has 5594 tests.\n"
            "Exposes 52 memory tools today.\n"
            "Exposes 50 memory tools and 12 tests skipped [not-a-count-claim: tests]\n"
        )
        self.assertEqual(gate.check_counts(gate.TEST_CLAIM, 5594, "tests"), [])
        failures = gate.check_counts(gate.TOOL_CLAIM, 52, "tools")
        self.assertEqual(len(failures), 1)
        self.assertIn("advertises 50 tools", failures[0])

    def test_a_misspelled_exemption_does_not_exempt(self):
        """The marker fails closed: only the exact form silences a family."""
        for marker in (
            "[not-a-count-claim]",
            "[not-a-count-claim: Tests]",
            "[not a count claim: tests]",
            "[not-a-count-claim: tools]",
            "[not-a-count-claim:tests]",
        ):
            with self.subTest(marker=marker):
                self._install(f"The suite has 5594 tests.\n12 tests {marker} here\n")
                failures = gate.check_counts(gate.TEST_CLAIM, 5594, "tests")
                self.assertEqual(len(failures), 1)
                self.assertIn("advertises 12 tests", failures[0])

    def test_the_test_count_guard_fires_when_only_an_exemption_remains(self):
        """An exempt line must not stand in for the claim it is not.

        Before the marker existed, an incidental "12 tests" counted as a match
        and kept this guard silent even with every real claim deleted.
        """
        self._install("12 tests skipped [not-a-count-claim: tests] locally\n")
        failures = gate.check_counts(gate.TEST_CLAIM, 5594, "tests")
        self.assertEqual(len(failures), 1)
        self.assertIn("vacuously", failures[0])

    def test_the_with_integrations_claim_has_a_vacuity_guard(self):
        """It had a second, hand-rolled copy of the guard and no test."""
        self._install("no parenthetical here\n")
        failures = gate.check_counts(
            gate.TOOL_TOTAL_CLAIM, 55, "tools with integrations"
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("vacuously", failures[0])

    def test_the_registry_records_file_line_and_family(self):
        """The registry is the audit trail, so its shape is the contract."""
        self._install(
            "The suite has 5594 tests.\n"
            "12 tests skipped [not-a-count-claim: tests] locally\n"
            "and 3 more [not-a-count-claim: tools with integrations]\n"
        )
        self.assertEqual(
            gate.exemption_registry(),
            [("DOC.md", 2, "tests"), ("DOC.md", 3, "tools with integrations")],
        )

    def test_release_history_lines_declare_no_exemptions(self):
        """A history line is already skipped; it must not enter the registry."""
        self._install("**v4.13.0 — old.** 12 tests [not-a-count-claim: tests]\n")
        self.assertEqual(gate.exemption_registry(), [])

    def test_the_openssf_answers_are_scanned(self):
        """Its answers are transcribed into the badge questionnaire, so its
        numbers are claims about the present — unscanned, three of them drifted.
        """
        self.assertIn(".bestpractices.json", gate.SCANNED_FILES)


class VersionTests(unittest.TestCase):
    def setUp(self):
        self._real_read = gate.read

    def tearDown(self):
        gate.read = self._real_read

    def _install(self, manifest: str, badge: str | None):
        files = {
            "manifest.json": '{"version": "%s"}' % manifest,
            "server.json": '{"version": "4.16.0"}',
            "package.json": '{"version": "4.16.0"}',
        }
        if badge is not None:
            files["assets/badge-version.svg"] = f"<title>Version {badge}</title>"
        gate.read = _FakeRepo(**files).read

    def test_manifest_and_badge_must_match_pyproject(self):
        self._install(manifest="4.16.0", badge="4.16.0")
        self.assertEqual(gate.check_versions("4.16.0"), [])

    def test_stale_manifest_version_is_reported(self):
        self._install(manifest="4.15.0", badge="4.16.0")
        failures = gate.check_versions("4.16.0")
        self.assertEqual(len(failures), 1)
        self.assertIn("manifest.json", failures[0])

    def test_stale_committed_badge_is_reported(self):
        self._install(manifest="4.16.0", badge="4.15.0")
        failures = gate.check_versions("4.16.0")
        self.assertEqual(len(failures), 1)
        self.assertIn("version badge says 4.15.0", failures[0])

    def test_a_missing_badge_file_fails_closed(self):
        """Self-hosting moved the figure into a file that can be deleted.

        The URL-shaped predecessor of this check silently passed when its
        pattern stopped matching, so a gate that cannot find its subject must
        report rather than shrug.
        """
        self._install(manifest="4.16.0", badge=None)
        failures = gate.check_versions("4.16.0")
        self.assertEqual(len(failures), 1)
        self.assertIn("missing", failures[0])

    def test_a_badge_without_a_version_title_fails_closed(self):
        self._install(manifest="4.16.0", badge="4.16.0")
        gate.read = _FakeRepo(
            **{
                "manifest.json": '{"version": "4.16.0"}',
                "server.json": '{"version": "4.16.0"}',
                "package.json": '{"version": "4.16.0"}',
                "assets/badge-version.svg": "<svg><title>something else</title></svg>",
            }
        ).read
        failures = gate.check_versions("4.16.0")
        self.assertEqual(len(failures), 1)
        self.assertIn("diverged", failures[0])


class CollectFailuresTests(unittest.TestCase):
    """The composition: every family must reach the report.

    Only the real tree exercised this before, and the real tree is green — so
    a mutant that broke a whole family still passed. These drive it against a
    repository that is deliberately stale, one family at a time.
    """

    CONSISTENT = (
        "52 memory tools (55 total with upstream).\n"
        "A 2-reference bibliography of 36 mechanisms.\n"
        "The suite has 6260 tests.\n"
    )

    def setUp(self):
        self._real_read = gate.read
        self._real_files = gate.SCANNED_FILES

    def tearDown(self):
        gate.read = self._real_read
        gate.SCANNED_FILES = self._real_files

    def _install(self, doc: str, badge: str = "6260", readme: str | None = None):
        gate.read = _FakeRepo(
            **{
                "DOC.md": doc,
                "docs/mcp-tools.md": CATALOGUE,
                "tests_py/test_main.py": PINNED_TEST,
                "docs/papers/bibliography.md": BIBLIOGRAPHY,
                "pyproject.toml": '[project]\nversion = "4.16.0"\n',
                "manifest.json": '{"version": "4.16.0"}',
                "server.json": '{"version": "4.16.0"}',
                "package.json": '{"version": "4.16.0"}',
                "README.md": readme
                or '<img src="assets/badge-tests.svg" alt="tests">\n',
                "assets/badge-version.svg": "<title>Version 4.16.0</title>",
                "assets/badge-tests.svg": f"<title>{badge} tests passing</title>",
            }
        ).read
        gate.SCANNED_FILES = ("DOC.md",)

    def test_a_consistent_repository_reports_nothing(self):
        self._install(self.CONSISTENT)
        self.assertEqual(gate.collect_failures(test_count=6260), [])

    def test_each_family_reports_its_own_stale_claim(self):
        """One stale number per family, checked by the message it produces."""
        for old, new, expected in (
            ("52 memory tools", "50 memory tools", "advertises 50 tools,"),
            ("(55 total", "(53 total", "advertises 53 tools with integrations,"),
            ("2-reference", "3-reference", "advertises 3 references,"),
            ("36 mechanisms", "35 mechanisms", "advertises 35 mechanisms,"),
            ("6260 tests", "6259 tests", "advertises 6259 tests,"),
        ):
            with self.subTest(family=expected):
                self._install(self.CONSISTENT.replace(old, new))
                failures = gate.collect_failures(test_count=6260)
                self.assertEqual(len(failures), 1, failures)
                self.assertIn(expected, failures[0])

    def test_the_test_badge_is_checked_against_the_live_count(self):
        self._install(self.CONSISTENT, badge="6259")
        failures = gate.collect_failures(test_count=6260)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("tests badge says 6259", failures[0])

    def test_a_reintroduced_shields_hotlink_is_reported(self):
        """Self-hosting is only durable if reverting it is loud.

        A hotlinked badge is both a third-party beacon and a silent detachment
        of the claim from the checks above — the URL carries the figure, so the
        committed file stops being what the README shows.
        """
        self._install(
            self.CONSISTENT,
            readme='<img src="https://img.shields.io/badge/tests-1_passing.svg">\n',
        )
        failures = gate.collect_failures(test_count=6260)
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("hotlinked shields.io badge", failures[0])

    def test_without_a_live_count_the_test_family_is_not_checked(self):
        """The documented skip — and the reason it needs its own guard.

        ``--test-count`` is only passed by one matrix leg of one CI job, so a
        stale test count is invisible to every other caller of this script.
        Pinning the skip keeps that a deliberate property rather than a
        surprise; ``test_every_advertised_test_count_states_the_same_number``
        is what covers the family everywhere else.
        """
        self._install(self.CONSISTENT.replace("6260 tests", "1 tests"), badge="1")
        self.assertEqual(gate.collect_failures(test_count=None), [])


class RepositoryTests(unittest.TestCase):
    """The gate must pass on the tree it ships with — this is the gate itself."""

    def test_committed_docs_agree_with_the_repository(self):
        self.assertEqual(gate.collect_failures(test_count=None), [])

    def test_the_declared_exemptions_are_the_reviewed_set(self):
        """Naming every exemption here is what makes it an exemption.

        An undeclared marker, or one moved onto a line that really does state
        the suite size, fails this test — so the hole stays auditable rather
        than becoming a way to quietly silence the gate.

        The one member: CONTRIBUTING.md's install block reports how many tests
        SKIP when the optional extras are missing (measured 2026-07-28, #220).
        That is a true, dated measurement of something other than the suite
        size, and `TEST_CLAIM` cannot tell the two apart from the wording. It
        is declared rather than reworded, because rewording a real measurement
        to keep a gate quiet hides the measurement instead of fixing the gate.
        """
        self.assertEqual(
            [(p, label) for p, _, label in gate.exemption_registry()],
            [("CONTRIBUTING.md", "tests")],
        )

    def test_every_advertised_test_count_states_the_same_number(self):
        """The test-count family, checked without a live pytest collection.

        ``collect_failures`` skips TEST_CLAIM entirely when no --test-count is
        passed, so the only place it was ever exercised was one matrix leg of
        one CI job. Agreement between the sites needs no canonical value, so
        this runs everywhere and catches a half-updated count locally.
        """
        counts = {value for _, _, value in gate.scan_claims(gate.TEST_CLAIM, "tests")}
        self.assertEqual(len(counts), 1, f"advertised test counts disagree: {counts}")


class StructuralIntegrityTests(unittest.TestCase):
    """The scanned files must still say ONE thing, and JSON must still parse.

    Regression cover for the 2026-07-29 finding: `.bestpractices.json` was
    committed with four unresolved conflict blocks and passed the entire gate,
    because every check was a claim regex that matched the first side. These
    tests fail against that pre-fix gate, which had neither function.
    """

    def setUp(self):
        self._real_read = gate.read
        self._real_scanned = gate.SCANNED_FILES

    def tearDown(self):
        gate.read = self._real_read
        gate.SCANNED_FILES = self._real_scanned

    def _install(self, **files: str):
        gate.SCANNED_FILES = tuple(files)
        gate.read = _FakeRepo(**files).read

    def test_conflict_markers_are_reported_with_path_and_line(self):
        self._install(
            **{
                ".bestpractices.json": (
                    "{\n"
                    '<<<<<<< HEAD\n'
                    '  "test_justification": "6414 tests",\n'
                    "=======\n"
                    '  "test_justification": "6376 tests",\n'
                    ">>>>>>> origin/main\n"
                    "}\n"
                )
            }
        )
        failures = gate.check_no_conflict_markers()
        self.assertEqual(len(failures), 2, failures)
        self.assertIn(".bestpractices.json:2:", failures[0])
        self.assertIn("unresolved merge conflict marker", failures[0])
        self.assertIn(".bestpractices.json:6:", failures[1])

    def test_a_clean_file_reports_nothing(self):
        self._install(**{"README.md": "# Cortex\n\nAll 6417 tests pass.\n"})
        self.assertEqual(gate.check_no_conflict_markers(), [])

    def test_a_markdown_setext_underline_is_not_a_conflict_marker(self):
        """`=======` is a legal setext H1 rule, and most scanned files are
        Markdown. Matching the bare separator would fail honest documents, so
        only the labelled `<<<<<<< ref` / `>>>>>>> ref` lines are matched.
        """
        self._install(**{"docs/ROADMAP.md": "Roadmap\n=======\n\nNext up.\n"})
        self.assertEqual(gate.check_no_conflict_markers(), [])

    def test_a_missing_scanned_file_fails_closed(self):
        """A check that silently skips its subject still prints OK — the
        failure mode the badge check was rewritten to remove.
        """
        gate.SCANNED_FILES = ("GONE.md",)
        gate.read = _FakeRepo().read
        failures = gate.check_no_conflict_markers()
        self.assertEqual(len(failures), 1)
        self.assertIn("GONE.md: missing", failures[0])

    def test_unparseable_json_is_reported(self):
        self._install(**{".bestpractices.json": '{"a": 1,\n<<<<<<< HEAD\n}\n'})
        failures = gate.check_scanned_json_parses()
        self.assertEqual(len(failures), 1, failures)
        self.assertIn(".bestpractices.json: not valid JSON", failures[0])

    def test_valid_json_reports_nothing(self):
        self._install(**{".bestpractices.json": '{"test_status": "Met"}\n'})
        self.assertEqual(gate.check_scanned_json_parses(), [])

    def test_markdown_is_not_json_checked(self):
        """Only `.json` members of SCANNED_FILES are parsed; a Markdown file
        that happens to start with a brace must not be reported.
        """
        self._install(**{"README.md": "{ this is prose, not JSON\n"})
        self.assertEqual(gate.check_scanned_json_parses(), [])

    def test_both_checks_run_inside_collect_failures(self):
        """Wiring guard: a function that is never called proves nothing. The
        conflicted file below is reported by BOTH new checks through the
        public entry point.
        """
        gate.SCANNED_FILES = (".bestpractices.json",)
        gate.read = _FakeRepo(
            **{".bestpractices.json": '{\n<<<<<<< HEAD\n"a": 1\n>>>>>>> theirs\n}\n'}
        ).read
        reported = "\n".join(gate.check_no_conflict_markers())
        self.assertIn("unresolved merge conflict marker", reported)
        self.assertIn("not valid JSON", "\n".join(gate.check_scanned_json_parses()))

    def test_the_real_repository_tree_is_structurally_clean(self):
        """Runs against the actual files, not a double — this is the assertion
        that would have caught the committed markers in the working tree.
        """
        self.assertEqual(gate.check_no_conflict_markers(), [])
        self.assertEqual(gate.check_scanned_json_parses(), [])


if __name__ == "__main__":
    unittest.main()
