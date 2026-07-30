"""Tests for scripts/generate_repo_badges.py — the self-hosted badge gate.

Written unittest-style to match the sibling script gates; Cortex's pytest
collects unittest classes natively.

The property under test throughout is that a committed badge cannot quietly
disagree with the repository. The badges exist as files precisely so no third
party can restate the claim; that only holds if a file drifting from its
source is a RED CI run rather than a silent inaccuracy, so every path below
asserts the drift is reported.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from xml.etree import ElementTree

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Dotted to match the path-derived name mutmut keys mutant trampolines on
# ("scripts.generate_repo_badges.*") — a bare module name makes every mutant
# look unreached to a scoped mutation run (issue #262).
_spec = importlib.util.spec_from_file_location(
    "scripts.generate_repo_badges", _SCRIPTS / "generate_repo_badges.py"
)
gen = importlib.util.module_from_spec(_spec)
# Register before exec: @dataclass resolves its owning module through
# sys.modules, and RepoBadge is defined at import time.
sys.modules[_spec.name] = gen
_spec.loader.exec_module(gen)

# Loaded under its own dotted name, separately from generate_repo_badges.py's
# internal bare `import badge_render` (which this exec_module call above just
# triggered, caching a SECOND copy in sys.modules["badge_render"] bare): the
# two direct-call tests below (test_markup_bearing_text_is_escaped,
# test_a_double_hyphen_in_provenance_is_refused) are badge_render.py's only
# exercise of its escaping/validation logic, and mutmut keys mutant
# trampolines on the path-derived "scripts.badge_render.*" — calling through
# the bare-cached copy would make every mutant there look unreached, so a
# scoped mutation run on this file would stop early instead of scoring it
# (issue #262). generate_repo_badges.py's own bare import is unaffected: it
# keeps using its separately-cached bare copy, exactly like the
# launcher.py/launcher_deps.py precedent.
_badge_render_spec = importlib.util.spec_from_file_location(
    "scripts.badge_render", _SCRIPTS / "badge_render.py"
)
badge_render = importlib.util.module_from_spec(_badge_render_spec)
sys.modules[_badge_render_spec.name] = badge_render
_badge_render_spec.loader.exec_module(badge_render)

PYPROJECT = (
    '[project]\nversion = "4.16.0"\nlicense = "MIT"\nrequires-python = ">=3.10"\n'
)

BIBLIOGRAPHY = "## References\n\n- Author, A. (2020). One.\n- Author, B. (2021). Two.\n"


class _FakeRepo:
    """Minimal stand-in for the repository files the generator reads."""

    def __init__(self, **files: str):
        self.files = files

    def read(self, relative_path: str) -> str:
        try:
            return self.files[relative_path]
        except KeyError:
            raise FileNotFoundError(relative_path) from None


class _CanonicalSourceTestCase(unittest.TestCase):
    """Shared fixture: the generator reads canonical values through the gate."""

    def setUp(self):
        self._real_read = gen.check_doc_claims.read
        gen.check_doc_claims.read = _FakeRepo(
            **{
                "pyproject.toml": PYPROJECT,
                "docs/papers/bibliography.md": BIBLIOGRAPHY,
            }
        ).read

    def tearDown(self):
        gen.check_doc_claims.read = self._real_read


class CanonicalReaderTests(_CanonicalSourceTestCase):
    def test_licence_comes_from_the_packaging_metadata(self):
        self.assertEqual(gen.canonical_licence(), "MIT")

    def test_python_floor_comes_from_requires_python(self):
        self.assertEqual(gen.canonical_python_floor(), "3.10")

    def test_a_missing_licence_is_an_error_not_a_guess(self):
        gen.check_doc_claims.read = _FakeRepo(
            **{"pyproject.toml": '[project]\nversion = "4.16.0"\n'}
        ).read
        with self.assertRaises(gen.check_doc_claims.ClaimError) as ctx:
            gen.canonical_licence()
        self.assertEqual(
            str(ctx.exception), "pyproject.toml: [project].license not found"
        )

    def test_a_missing_python_floor_is_an_error_not_a_guess(self):
        gen.check_doc_claims.read = _FakeRepo(
            **{"pyproject.toml": '[project]\nversion = "4.16.0"\n'}
        ).read
        with self.assertRaises(gen.check_doc_claims.ClaimError) as ctx:
            gen.canonical_python_floor()
        self.assertEqual(
            str(ctx.exception), 'pyproject.toml: requires-python ">=X.Y" not found'
        )

    def test_licence_supports_pyprojects_inline_table_form(self):
        """PEP 621 also allows `license = {text = "..."}`; both forms are read.

        Neither existing fixture nor the primary-form test above ever
        reaches this branch — it is the one this generator's own
        pyproject.toml does NOT use, so it had never been exercised for
        real (issue #262: a mutation of this literal pattern survived
        every prior run).
        """
        gen.check_doc_claims.read = _FakeRepo(
            **{"pyproject.toml": '[project]\nlicense = {text = "Apache-2.0"}\n'}
        ).read
        self.assertEqual(gen.canonical_licence(), "Apache-2.0")

    def test_licence_reads_the_first_declaration_when_two_are_present(self):
        """Pins `partition` (first match) over `rpartition` (last match).

        A single well-formed pyproject.toml never repeats the key, so this
        is a deliberate, narrow regression pin rather than a realistic
        scenario — but the choice is real: a stray duplicate must not
        silently read the LATER value.
        """
        gen.check_doc_claims.read = _FakeRepo(
            **{"pyproject.toml": 'license = "First"\nlicense = "Second"\n'}
        ).read
        self.assertEqual(gen.canonical_licence(), "First")

    def test_python_floor_reads_the_first_declaration_when_two_are_present(self):
        gen.check_doc_claims.read = _FakeRepo(
            **{
                "pyproject.toml": 'requires-python = ">=3.10"\n'
                'requires-python = ">=3.11"\n'
            }
        ).read
        self.assertEqual(gen.canonical_python_floor(), "3.10")


class BuildTests(_CanonicalSourceTestCase):
    def test_every_badge_states_its_canonical_value(self):
        by_name = {b.filename: b for b in gen.build_badges(test_count=42)}
        self.assertEqual(by_name["badge-license.svg"].message, "MIT")
        self.assertEqual(by_name["badge-python.svg"].message, "3.10+")
        self.assertEqual(by_name["badge-version.svg"].message, "4.16.0")
        self.assertEqual(by_name["badge-references.svg"].message, "2 papers")
        self.assertEqual(by_name["badge-tests.svg"].message, "42 passing")

    def test_the_tests_badge_carries_its_full_declared_shape(self):
        """message alone (above) does not pin label/fill/derivation — a
        mutation of any of those three previously survived every run."""
        by_name = {b.filename: b for b in gen.build_badges(test_count=42)}
        tests_badge = by_name["badge-tests.svg"]
        self.assertEqual(tests_badge.label, "tests")
        self.assertEqual(tests_badge.fill, gen._HEALTHY)
        self.assertEqual(
            tests_badge.derivation, "Source: the count pytest collects on this tree."
        )

    def test_without_a_live_count_no_test_badge_is_built(self):
        """A test count cannot be read off a file, so it is never assumed.

        Writing one from an assumption is how a committed badge becomes a
        confident false claim — the failure mode self-hosting exists to avoid.
        """
        names = {b.filename for b in gen.build_badges(test_count=None)}
        self.assertNotIn("badge-tests.svg", names)
        self.assertIn("badge-version.svg", names)

    def test_every_badge_carries_its_derivation_in_the_file(self):
        for badge in gen.build_badges(test_count=42):
            with self.subTest(badge=badge.filename):
                self.assertIn("GENERATED by", gen.repo_badge_svg(badge))
                self.assertIn("Source:", gen.repo_badge_svg(badge))


class RenderTests(_CanonicalSourceTestCase):
    def test_every_badge_is_well_formed_xml(self):
        for badge in gen.build_badges(test_count=42):
            with self.subTest(badge=badge.filename):
                ElementTree.fromstring(gen.repo_badge_svg(badge))

    def test_the_title_states_the_claim_for_screen_readers(self):
        by_name = {b.filename: b for b in gen.build_badges(test_count=42)}
        root = ElementTree.fromstring(gen.repo_badge_svg(by_name["badge-tests.svg"]))
        title = root.find("{http://www.w3.org/2000/svg}title")
        self.assertEqual(title.text, "42 tests passing")
        self.assertEqual(root.get("aria-label"), "42 tests passing")

    def test_markup_bearing_text_is_escaped(self):
        """The one bug this badge family has shipped was an unescaped '<'.

        It reached the markup from a rendered value, not from a literal, so the
        guard belongs on a value that contains markup rather than on any
        particular caller.
        """
        spec = badge_render.BadgeSpec(
            label=badge_render.label_panel("a<b", "#000", "#fff"),
            message='x>y & "z"',
            message_fill="#111",
            message_text_fill="#fff",
            alt='alt<>&"',
            provenance=(),
        )
        rendered = badge_render.render(spec)
        ElementTree.fromstring(rendered)
        self.assertNotIn("<b", rendered.split("<title>")[1].split("</title>")[0])

    def test_a_double_hyphen_in_provenance_is_refused(self):
        """Regression: "--" is illegal inside an XML comment.

        The first cut of this generator described its own gate as
        ``--check`` and its source as ``pytest --collect-only``. Both landed
        inside the provenance comment and made all five badges unparseable —
        escaping the TEXT runs does not help, because the defect is in the
        comment. The renderer now validates the finished artifact, so any
        future wording that breaks it fails loudly here instead of shipping.
        """
        spec = badge_render.BadgeSpec(
            label=badge_render.label_panel("x", "#000", "#fff"),
            message="y",
            message_fill="#111",
            message_text_fill="#fff",
            alt="x y",
            provenance=("  <!-- run with --check -->",),
        )
        with self.assertRaises(badge_render.BadgeMarkupError):
            badge_render.render(spec)

    def test_every_committed_badge_on_disk_is_well_formed(self):
        """The guard above protects generation; this protects what shipped."""
        for path in sorted((Path(gen.REPO_ROOT) / "assets").glob("badge-*.svg")):
            with self.subTest(badge=path.name):
                ElementTree.parse(path)


class CheckModeTests(_CanonicalSourceTestCase):
    """--check is the blocking CI gate; it must never write, and must fail."""

    def setUp(self):
        super().setUp()
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)
        self._patch = mock.patch.object(gen, "REPO_ROOT", self._root)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()
        super().tearDown()

    def _written(self) -> set[str]:
        return {p.name for p in (self._root / "assets").glob("*.svg")}

    def test_a_missing_badge_is_reported_and_nothing_is_written(self):
        self.assertEqual(gen.main(["--check", "--test-count", "42"]), 1)
        self.assertEqual(self._written(), set())

    def test_generation_then_check_is_clean(self):
        self.assertEqual(gen.main(["--test-count", "42"]), 0)
        self.assertEqual(gen.main(["--check", "--test-count", "42"]), 0)

    def test_a_hand_edited_badge_is_reported_as_stale(self):
        gen.main(["--test-count", "42"])
        target = self._root / "assets" / "badge-version.svg"
        target.write_text(target.read_text().replace("4.16.0", "9.9.9"))
        self.assertEqual(gen.main(["--check", "--test-count", "42"]), 1)

    def test_check_does_not_repair_the_file_it_rejects(self):
        """--check reports; only a real run writes.

        A check that silently fixed the tree would turn a CI failure into a
        no-op on a developer's machine and let the drift ship.
        """
        gen.main(["--test-count", "42"])
        target = self._root / "assets" / "badge-version.svg"
        tampered = target.read_text().replace("4.16.0", "9.9.9")
        target.write_text(tampered)
        gen.main(["--check", "--test-count", "42"])
        self.assertEqual(target.read_text(), tampered)

    def test_a_drifted_count_is_rewritten_on_a_real_run(self):
        gen.main(["--test-count", "42"])
        self.assertEqual(gen.main(["--test-count", "43"]), 0)
        body = (self._root / "assets" / "badge-tests.svg").read_text()
        self.assertIn("43 tests passing", body)

    def test_an_unreadable_canonical_source_exits_two_not_one(self):
        """A gate that cannot run is distinct from a gate that found drift."""
        gen.check_doc_claims.read = _FakeRepo().read
        self.assertEqual(gen.main(["--check", "--test-count", "42"]), 2)

    def test_an_under_claiming_tests_badge_passes_check(self):
        """The floor invariant (issue #287): a badge committed for a lower,
        earlier count stays green once the live count only grows — the
        property that lets a PR add tests without touching this file."""
        gen.main(["--test-count", "42"])
        self.assertEqual(gen.main(["--check", "--test-count", "44"]), 0)

    def test_an_over_claiming_tests_badge_fails_check(self):
        gen.main(["--test-count", "44"])
        self.assertEqual(gen.main(["--check", "--test-count", "42"]), 1)


class StaleTestsBadgeTests(_CanonicalSourceTestCase):
    """Direct tests of stale_tests_badge — the floor check itself.

    CheckModeTests exercises it only through main(); these pin every one of
    its branches for mutation coverage (issue #287).
    """

    def setUp(self):
        super().setUp()
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)
        self._patch = mock.patch.object(gen, "REPO_ROOT", self._root)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def _commit(self, test_count: int) -> None:
        gen.write(gen.RepoBadge(**gen.repo_badge_catalog.tests_badge_spec(test_count)))

    def test_missing_badge_is_reported(self):
        self.assertIn("missing", gen.stale_tests_badge(42))

    def test_a_title_without_a_count_is_reported(self):
        target = self._root / "assets" / "badge-tests.svg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("<svg><title>not a count</title></svg>")
        self.assertIn("no test-count figure", gen.stale_tests_badge(42))

    def test_an_exact_match_is_not_reported(self):
        self._commit(42)
        self.assertIsNone(gen.stale_tests_badge(42))

    def test_an_under_claim_is_not_reported(self):
        self._commit(41)
        self.assertIsNone(gen.stale_tests_badge(42))

    def test_an_over_claim_is_reported(self):
        self._commit(43)
        reason = gen.stale_tests_badge(42)
        self.assertIn("43", reason)
        self.assertIn("exceeding the live count of 42", reason)

    def test_structural_drift_still_fails_even_at_a_valid_floor(self):
        """A hand-edited label/colour must still fail — the floor loosens
        only the number, never label/colour/provenance drift."""
        self._commit(41)
        target = self._root / "assets" / "badge-tests.svg"
        target.write_text(target.read_text().replace("tests", "TESTS", 1))
        self.assertIsNotNone(gen.stale_tests_badge(42))


class WriteAndStaleTests(unittest.TestCase):
    """Direct tests of write()/stale() — the file I/O this gate performs.

    CheckModeTests exercises these only through main(), which never asserts
    their return value or message content directly; a flipped True/False or
    a None-path bug in either function previously survived every run.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)
        self._patch = mock.patch.object(gen, "REPO_ROOT", self._root)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(self._tmp.cleanup)
        self.badge = gen.RepoBadge(
            filename="badge-x.svg",
            label="x",
            message="y",
            fill="#111",
            alt="x y",
            derivation="Source: a test fixture.",
        )

    def _target(self) -> Path:
        return self._root / "assets" / "badge-x.svg"

    def test_write_reports_true_and_creates_the_file_on_first_write(self):
        self.assertTrue(gen.write(self.badge))
        self.assertEqual(
            self._target().read_text(encoding="utf-8"),
            gen.repo_badge_svg(self.badge),
        )

    def test_write_reports_false_and_leaves_the_file_untouched_when_unchanged(self):
        gen.write(self.badge)
        mtime_before = self._target().stat().st_mtime_ns
        self.assertFalse(gen.write(self.badge))
        self.assertEqual(self._target().stat().st_mtime_ns, mtime_before)

    def test_write_creates_every_missing_parent_level(self):
        """`parents=True` matters exactly when REPO_ROOT's own tree is
        fresh (e.g. a first checkout, before even the repo directory
        exists) — a single-level `assets/` miss under an existing
        REPO_ROOT cannot distinguish `parents=True` from `False`/`None`."""
        nested_root = self._root / "not-yet-created" / "nested"
        with mock.patch.object(gen, "REPO_ROOT", nested_root):
            self.assertTrue(gen.write(self.badge))
            self.assertTrue((nested_root / "assets" / "badge-x.svg").exists())

    def test_write_pins_utf8_on_both_the_read_and_the_write(self):
        """A locale-dependent default would make a byte-identical file read
        differently on a contributor's machine than in CI; both calls to
        Path here must pin the encoding explicitly, never rely on default."""
        gen.write(self.badge)  # first write, so the 2nd call's read is real
        with mock.patch.object(
            Path, "read_text", autospec=True, side_effect=Path.read_text
        ) as read_spy:
            gen.write(self.badge)
        self.assertEqual(read_spy.call_args.kwargs.get("encoding"), "utf-8")
        with mock.patch.object(
            Path, "write_text", autospec=True, side_effect=Path.write_text
        ) as write_spy:
            gen.write(gen.RepoBadge(**{**vars(self.badge), "message": "changed"}))
        self.assertEqual(write_spy.call_args.kwargs.get("encoding"), "utf-8")

    def test_stale_names_the_missing_files_own_path(self):
        self.assertEqual(
            gen.stale(self.badge),
            f"{gen.repo_badge_path(self.badge)}: missing"
            " — run scripts/generate_repo_badges.py",
        )

    def test_stale_names_the_stale_files_own_path_and_new_value(self):
        gen.write(self.badge)
        self._target().write_text("<svg>tampered</svg>", encoding="utf-8")
        self.assertEqual(
            gen.stale(self.badge),
            f"{gen.repo_badge_path(self.badge)}: stale (x is now 'y')"
            " — run scripts/generate_repo_badges.py",
        )

    def test_stale_reads_with_utf8(self):
        gen.write(self.badge)
        with mock.patch.object(
            Path, "read_text", autospec=True, side_effect=Path.read_text
        ) as read_spy:
            gen.stale(self.badge)
        self.assertEqual(read_spy.call_args.kwargs.get("encoding"), "utf-8")

    def test_stale_is_none_once_current(self):
        gen.write(self.badge)
        self.assertIsNone(gen.stale(self.badge))


class MainMessagesTests(_CanonicalSourceTestCase):
    """Every printed line IS the gate's user-visible contract (§13 F1): a
    wrong message misleads whoever reads a red CI run."""

    def setUp(self):
        super().setUp()
        self._tmp = TemporaryDirectory()
        self._root = Path(self._tmp.name)
        self._patch = mock.patch.object(gen, "REPO_ROOT", self._root)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.addCleanup(self._tmp.cleanup)

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gen.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_real_run_names_each_written_file_and_the_total(self):
        badges = gen.build_badges(test_count=42)
        code, out, err = self._run(["--test-count", "42"])
        self.assertEqual(code, 0)
        for badge in badges:
            self.assertIn(f"wrote {gen.repo_badge_path(badge)}", out)
        self.assertIn(f"{len(badges)} of {len(badges)} badge(s) changed", out)
        self.assertEqual(err, "")

    def test_check_reports_ok_with_the_exact_checked_count(self):
        badges = gen.build_badges(test_count=42)
        self._run(["--test-count", "42"])
        code, out, err = self._run(["--check", "--test-count", "42"])
        self.assertEqual(code, 0)
        self.assertEqual(out, f"badges OK ({len(badges)} checked)\n")
        self.assertEqual(err, "")

    def test_check_failure_prints_the_header_and_every_failure_line(self):
        badges = gen.build_badges(test_count=42)
        code, out, err = self._run(["--check", "--test-count", "42"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        lines = err.splitlines()
        self.assertEqual(lines[0], "Committed badges disagree with the repository:")
        for badge in badges:
            self.assertIn(f"  {gen.repo_badge_path(badge)}: missing", err)

    def test_an_unreadable_source_names_the_underlying_error(self):
        gen.check_doc_claims.read = _FakeRepo().read
        code, out, err = self._run(["--check", "--test-count", "42"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("badge generation could not run: "))
        self.assertIn("pyproject.toml", err)


class ArgparseContractTests(unittest.TestCase):
    """The CLI surface (--help text, --test-count typing) is observable
    behaviour too — a cosmetic-looking help string is what a contributor
    reads to learn the gate exists at all.

    Asserted against the parser's own Action objects, exact-equality, not
    against rendered `--help` text: argparse re-wraps at word boundaries
    (fragile to assert against) and a `assertIn` on rendered text cannot
    distinguish "the real string" from mutmut's "XXthe real stringXX"
    marker mutation, since the original text still appears as a substring
    of the wrapped one.
    """

    def _actions_by_flag(self) -> dict[str, object]:
        parser = gen._build_parser()
        return {a.option_strings[0]: a for a in parser._actions if a.option_strings}

    def test_help_documents_the_generator_and_both_flags_exactly(self):
        parser = gen._build_parser()
        self.assertEqual(parser.description, gen.__doc__)
        actions = self._actions_by_flag()
        self.assertEqual(
            actions["--check"].help,
            "do not write; exit 1 if any badge is missing or stale",
        )
        self.assertEqual(
            actions["--test-count"].help,
            "live test count (from `pytest --collect-only -q`); badge skipped"
            " when absent",
        )
        self.assertIs(actions["--test-count"].type, int)

    def test_a_non_integer_test_count_is_rejected_not_stored_as_text(self):
        """type=int is a real contract: without it a typo'd count would
        silently become the badge's message text instead of failing
        argument parsing before any file is touched."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                gen.main(["--test-count", "not-a-number"])
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("--test-count", err.getvalue())


class RepositoryTests(unittest.TestCase):
    """The committed badges must match the tree they ship with."""

    def test_committed_badges_agree_with_the_repository(self):
        self.assertEqual(gen.main(["--check"]), 0)

    def test_the_readme_shows_the_committed_files(self):
        readme = (Path(gen.REPO_ROOT) / "README.md").read_text()
        for badge in gen.build_badges(test_count=None):
            with self.subTest(badge=badge.filename):
                self.assertIn(f"assets/{badge.filename}", readme)

    def test_the_readme_hotlinks_no_shields_badge(self):
        readme = (Path(gen.REPO_ROOT) / "README.md").read_text()
        self.assertNotIn("img.shields.io", readme)

    def test_the_live_status_badges_stay_live(self):
        """CI status and OpenSSF are NOT converted, and that is load-bearing.

        Both report an external system's current verdict. A committed copy
        would assert a standing we might no longer hold — stale is tolerable
        for a dated claim, false is not for a live one.
        """
        readme = (Path(gen.REPO_ROOT) / "README.md").read_text()
        self.assertIn("actions/workflows/ci.yml/badge.svg", readme)
        self.assertIn("bestpractices.dev/projects/13836/badge", readme)
