"""Tests for scripts/check_doc_claims.py — the doc-claim gate.

The gate's own failure mode is silence: a regex that stops matching, or a
canonical source it cannot read, would let every claim drift unnoticed. These
tests pin both the detection (a wrong number fails) and the vacuity guard (no
claim at all fails), plus the history exemption that keeps release notes from
being rewritten.
"""

from __future__ import annotations

import codecs
import contextlib
import importlib.util
import io
import sys
import unittest
import unittest.mock
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


@contextlib.contextmanager
def _spying_on_argparse_construction(captured: dict):
    """Capture `main()`'s `ArgumentParser(description=...)` and its
    `--test-count` `add_argument(help=...)` into `captured`, without
    breaking argparse's own recursive `super()` call.

    argparse's `ArgumentParser.__init__` does `super(ArgumentParser, self)`
    (an explicit, not zero-arg, super — CPython 3.12 argparse.py:1788),
    which re-resolves the name `ArgumentParser` as a fresh global lookup on
    every call. Replacing the `argparse.ArgumentParser` module attribute
    (e.g. with a subclass) makes that lookup hit the replacement and
    recurse forever; patching only the class's own `__init__`/
    `add_argument` methods leaves the attribute — and that lookup —
    untouched.
    """
    real_init = gate.argparse.ArgumentParser.__init__
    real_add_argument = gate.argparse.ArgumentParser.add_argument

    def spy_init(self, *args, **kwargs):
        captured["description"] = kwargs.get("description")
        return real_init(self, *args, **kwargs)

    def spy_add_argument(self, *args, **kwargs):
        if args and args[0] == "--test-count":
            captured["help"] = kwargs.get("help")
        return real_add_argument(self, *args, **kwargs)

    with (
        unittest.mock.patch.object(gate.argparse.ArgumentParser, "__init__", spy_init),
        unittest.mock.patch.object(
            gate.argparse.ArgumentParser, "add_argument", spy_add_argument
        ),
    ):
        yield


class ReadTests(unittest.TestCase):
    """`read()` is the one function every canonical-source helper funnels
    through, so its own contract — decode as UTF-8, explicitly — needs its
    own test rather than relying on every caller's fixture to expose it.

    ``encoding=None`` falls back to `locale.getpreferredencoding`, which is
    not guaranteed to be UTF-8 (a minimal POSIX locale reports "ascii"); the
    canonical sources this reads (bibliography.md, README.md) carry non-ASCII
    prose (em dashes, accented author names), so an implicit locale decode is
    a latent corruption bug, not a style nit.
    """

    def test_read_decodes_explicitly_as_utf8(self):
        seen_encodings = []
        real_read_text = Path.read_text

        def spy(self, *args, **kwargs):
            seen_encodings.append(kwargs.get("encoding"))
            return real_read_text(self, *args, **kwargs)

        with unittest.mock.patch.object(Path, "read_text", spy):
            gate.read("README.md")

        self.assertEqual(len(seen_encodings), 1)
        self.assertIsNotNone(
            seen_encodings[0], "encoding must be explicit, not locale-default"
        )
        # Codec names are case/hyphen-insensitive in CPython (PEP 263), so
        # "UTF-8" and "utf-8" are the same codec — comparing normalized names
        # keeps this test from failing on that harmless casing. This is also
        # the documented-equivalent rationale (coding-standards.md §12.1) for
        # the one mutant this test does not and should not kill: mutmut's
        # `x_read__mutmut_4` rewrites the literal to `encoding="UTF-8"`,
        # which `codecs.lookup` resolves to the identical "utf-8" codec —
        # verified: `codecs.lookup("utf-8").name == codecs.lookup("UTF-8").name`
        # is `True` on CPython. No observable behaviour differs, so no test
        # can or should distinguish it from the original.
        self.assertEqual(codecs.lookup(seen_encodings[0]).name, "utf-8")


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

    def test_missing_standalone_total_sentence_is_an_error(self):
        """The header sentence the whole function's regex hunts for.

        No sentence at all is a different failure than a wrong number in it
        — the message must name the file and what was expected there.
        """
        self._install(
            **{
                "docs/mcp-tools.md": "No counts stated here.\n",
                "tests_py/test_main.py": PINNED_TEST,
            }
        )
        with self.assertRaises(gate.ClaimError) as caught:
            gate.canonical_tool_counts()
        self.assertEqual(
            str(caught.exception),
            "docs/mcp-tools.md: standalone/total tool sentence not found",
        )

    def test_inconsistent_arithmetic_in_the_catalogue_is_an_error(self):
        broken = CATALOGUE.replace("(55 total", "(56 total")
        self._install(
            **{"docs/mcp-tools.md": broken, "tests_py/test_main.py": PINNED_TEST}
        )
        with self.assertRaises(gate.ClaimError) as caught:
            gate.canonical_tool_counts()
        self.assertEqual(str(caught.exception), "docs/mcp-tools.md: 52 + 3 != 56")

    def test_missing_pinned_registry_test_is_an_error(self):
        """The pinned-test regex against tests_py/test_main.py, unmatched.

        Distinct from the drift case above: here the pinned test itself is
        gone (renamed, deleted), not merely disagreeing with the catalogue.
        """
        self._install(
            **{
                "docs/mcp-tools.md": CATALOGUE,
                "tests_py/test_main.py": "def test_something_else(self):\n",
            }
        )
        with self.assertRaises(gate.ClaimError) as caught:
            gate.canonical_tool_counts()
        self.assertEqual(
            str(caught.exception),
            "tests_py/test_main.py: pinned tool-count test not found",
        )

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

    def test_the_first_references_heading_is_the_split_point(self):
        """`split(..., 1)` on the FIRST occurrence, not `rsplit` on the last.

        A doubled "## References" heading (a copy-paste mistake, or a nested
        subsection literally named that) must not silently move which text
        counts as entries: everything after the first heading is the section,
        including a second stray heading line (excluded by the `#` filter,
        same as any other heading) and the entries that follow it.
        """
        self._install(
            **{
                "docs/papers/bibliography.md": (
                    "36 mechanisms.\n\n## References\n\n"
                    "Author, A. (2001). One.\n\n## References\n\n"
                    "Author, B. (2002). Two.\n"
                )
            }
        )
        self.assertEqual(gate.canonical_reference_count(), 2)

    def test_bibliography_without_a_references_section_is_an_error(self):
        self._install(**{"docs/papers/bibliography.md": "# Bibliography\n"})
        with self.assertRaises(gate.ClaimError) as caught:
            gate.canonical_reference_count()
        self.assertEqual(
            str(caught.exception),
            "docs/papers/bibliography.md: '## References' section not found",
        )

    def test_a_references_section_with_no_entries_is_an_error(self):
        """A heading with nothing under it — only furniture, no citations."""
        self._install(
            **{
                "docs/papers/bibliography.md": (
                    "36 mechanisms.\n\n## References\n\n### Neuroscience\n\n---\n"
                )
            }
        )
        with self.assertRaises(gate.ClaimError) as caught:
            gate.canonical_reference_count()
        self.assertEqual(
            str(caught.exception),
            "docs/papers/bibliography.md: no reference entries found",
        )

    def test_mechanism_count_is_read_from_the_bibliography_header(self):
        self._install(**{"docs/papers/bibliography.md": BIBLIOGRAPHY})
        self.assertEqual(gate.canonical_mechanism_count(), 36)

    def test_undeclared_mechanism_count_is_an_error(self):
        self._install(
            **{"docs/papers/bibliography.md": "# B\n\n## References\n\nA. (1)\n"}
        )
        with self.assertRaises(gate.ClaimError) as caught:
            gate.canonical_mechanism_count()
        self.assertEqual(
            str(caught.exception),
            "docs/papers/bibliography.md: no mechanism count declared",
        )

    def test_version_comes_from_pyproject(self):
        self._install(
            **{"pyproject.toml": '[project]\nname = "x"\nversion = "4.16.0"\n'}
        )
        self.assertEqual(gate.canonical_version(), "4.16.0")

    def test_missing_version_declaration_is_an_error(self):
        self._install(**{"pyproject.toml": '[project]\nname = "x"\n'})
        with self.assertRaises(gate.ClaimError) as caught:
            gate.canonical_version()
        self.assertEqual(
            str(caught.exception), "pyproject.toml: [project].version not found"
        )


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
        # Exact text, not just `assertIn("diverged", ...)` — a mutant that
        # corrupts the middle of the sentence while leaving "diverged" intact
        # would pass a substring check but ship a broken message.
        self.assertEqual(
            failures[0],
            "assets/badge-version.svg: no version figure in its <title>; the"
            " badge and this gate have diverged",
        )


class HotlinkedBadgeTests(unittest.TestCase):
    """`check_no_hotlinked_badges` line numbers and message, unit-level.

    Only exercised before through `collect_failures` with the hotlink on
    line 1, which cannot distinguish `start=1` from `start=0` — both report
    line 1 for a match there. Placing the hotlink on line 2 makes the
    reported number a real assertion instead of an accident of the fixture.
    """

    def setUp(self):
        self._real_read = gate.read

    def tearDown(self):
        gate.read = self._real_read

    def test_a_hotlink_on_a_later_line_is_reported_with_its_own_number(self):
        gate.read = _FakeRepo(
            **{
                "README.md": (
                    "# Cortex\n"
                    '<img src="https://img.shields.io/badge/tests-1_passing.svg">\n'
                )
            }
        ).read
        failures = gate.check_no_hotlinked_badges()
        self.assertEqual(len(failures), 1)
        self.assertEqual(
            failures[0],
            "README.md:2: hotlinked shields.io badge — these are"
            " committed under assets/ (scripts/generate_repo_badges.py)",
        )

    def test_no_hotlink_reports_nothing(self):
        gate.read = _FakeRepo(**{"README.md": "# Cortex\n\nAll clean.\n"}).read
        self.assertEqual(gate.check_no_hotlinked_badges(), [])


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
                    "<<<<<<< HEAD\n"
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

    def test_a_missing_file_does_not_abort_the_conflict_scan(self):
        """The missing-file handler is a `continue`, not a `break`: a
        missing file earlier in SCANNED_FILES must not stop a real conflict
        marker in a later file from being reported.
        """
        gate.SCANNED_FILES = ("GONE.md", "README.md")
        gate.read = _FakeRepo(
            **{"README.md": "# Cortex\n<<<<<<< HEAD\nours\n>>>>>>> theirs\n"}
        ).read
        failures = gate.check_no_conflict_markers()
        self.assertEqual(len(failures), 3, failures)
        self.assertIn("GONE.md: missing", failures[0])
        self.assertIn("README.md:2:", failures[1])
        self.assertIn("README.md:4:", failures[2])

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

    def test_a_missing_json_file_fails_closed(self):
        """`check_scanned_json_parses` has its own FileNotFoundError arm,
        separate from `check_no_conflict_markers`'s — each must fail closed.
        """
        gate.SCANNED_FILES = ("GONE.json",)
        gate.read = _FakeRepo().read
        failures = gate.check_scanned_json_parses()
        self.assertEqual(failures, ["GONE.json: missing — the doc-claim gate reads it"])

    def test_a_non_json_file_does_not_abort_the_json_scan(self):
        """The `.json`-suffix skip is a `continue`, not a `break`: a Markdown
        file earlier in SCANNED_FILES must not stop later `.json` members
        from being parsed.
        """
        self._install(**{"README.md": "prose\n", "bad.json": '{"a": 1,\n'})
        failures = gate.check_scanned_json_parses()
        self.assertEqual(len(failures), 1, failures)
        self.assertIn("bad.json: not valid JSON", failures[0])

    def test_a_missing_json_file_does_not_abort_the_json_scan(self):
        """The missing-file handler is a `continue`, not a `break`: a
        missing `.json` member earlier in SCANNED_FILES must not stop a
        later `.json` member from being checked.
        """
        gate.SCANNED_FILES = ("gone.json", "bad.json")
        gate.read = _FakeRepo(**{"bad.json": '{"a": 1,\n'}).read
        failures = gate.check_scanned_json_parses()
        self.assertEqual(len(failures), 2, failures)
        self.assertIn("gone.json: missing", failures[0])
        self.assertIn("bad.json: not valid JSON", failures[1])

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


class MainTests(unittest.TestCase):
    """`main()` — the CLI glue no other test reaches (the composition is
    always exercised through `collect_failures` directly), so every arm
    (abort, report, success) needs its own assertion on exit code and the
    stream it writes to.

    Documented-equivalent mutant (coding-standards.md §12.1): mutmut's
    `x_main__mutmut_8` deletes the `--test-count` argument's explicit
    ``default=None`` kwarg. `argparse` already defaults an unset optional
    argument to `None` when no `default` kwarg is given at all — verified:
    `ArgumentParser().add_argument("--test-count", type=int).parse_args([]).test_count`
    is `None` with or without the explicit kwarg. No observable behaviour
    differs, so no test can or should distinguish it from the original.
    """

    def setUp(self):
        self._real_collect = gate.collect_failures
        self._real_registry = gate.exemption_registry
        self._real_argv = sys.argv

    def tearDown(self):
        gate.collect_failures = self._real_collect
        gate.exemption_registry = self._real_registry
        sys.argv = self._real_argv

    def _run(self, argv):
        sys.argv = ["check_doc_claims.py", *argv]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate.main()
        return code, out.getvalue(), err.getvalue()

    def test_a_claim_error_aborts_to_stderr_with_exit_code_2(self):
        def boom(test_count):
            raise gate.ClaimError("bibliography.md unreadable")

        gate.collect_failures = boom
        code, out, err = self._run([])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(
            err, "doc-claim gate could not run: bibliography.md unreadable\n"
        )

    def test_failures_are_reported_to_stderr_with_exit_code_1(self):
        gate.collect_failures = lambda test_count: [
            "DOC.md:1: advertises 50 tools, canonical is 52"
        ]
        code, out, err = self._run([])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(
            err,
            "Documentation claims disagree with the repository:\n"
            "  DOC.md:1: advertises 50 tools, canonical is 52\n",
        )

    def test_success_reports_exemption_count_and_exit_code_0(self):
        gate.collect_failures = lambda test_count: []
        gate.exemption_registry = lambda: [("CONTRIBUTING.md", 5, "tests")]
        code, out, err = self._run([])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            out,
            "doc claims OK (1 declared not-a-claim exemption(s))\n"
            "  CONTRIBUTING.md:5: exempt from the tests claim\n",
        )

    def test_success_with_no_exemptions_reports_a_zero_count(self):
        gate.collect_failures = lambda test_count: []
        gate.exemption_registry = lambda: []
        code, out, _err = self._run([])
        self.assertEqual(code, 0)
        self.assertEqual(out, "doc claims OK (0 declared not-a-claim exemption(s))\n")

    def test_the_parser_declares_the_modules_docstring_and_flag_help(self):
        """The description/help text argparse formats for `--help`.

        Asserting on `--help`'s rendered output would depend on `textwrap`
        reflowing at the terminal's COLUMNS (a CI-integrity axis, coding-
        standards.md Move 7) rather than on the CLI's own contract, so this
        spies the raw strings handed to argparse before its formatter ever
        touches them — see `_spying_on_argparse_construction` for why that
        spy patches methods, not the `ArgumentParser` class attribute.
        """
        captured = {}
        with _spying_on_argparse_construction(captured):
            gate.collect_failures = lambda test_count: []
            gate.exemption_registry = lambda: []
            self._run([])

        self.assertEqual(captured["description"], gate.__doc__)
        self.assertEqual(
            captured["help"],
            "live test count (from `pytest --collect-only -q`); skipped when absent",
        )

    def test_the_test_count_flag_is_parsed_and_forwarded(self):
        seen = {}

        def fake(test_count):
            seen["test_count"] = test_count
            return []

        gate.collect_failures = fake
        gate.exemption_registry = lambda: []
        self._run(["--test-count", "1234"])
        self.assertEqual(seen["test_count"], 1234)

    def test_without_the_flag_test_count_is_none(self):
        seen = {}

        def fake(test_count):
            seen["test_count"] = test_count
            return []

        gate.collect_failures = fake
        gate.exemption_registry = lambda: []
        self._run([])
        self.assertIsNone(seen["test_count"])


if __name__ == "__main__":
    unittest.main()
