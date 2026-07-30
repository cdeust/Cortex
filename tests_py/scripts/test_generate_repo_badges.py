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

import importlib.util
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
        with self.assertRaises(gen.check_doc_claims.ClaimError):
            gen.canonical_licence()

    def test_a_missing_python_floor_is_an_error_not_a_guess(self):
        gen.check_doc_claims.read = _FakeRepo(
            **{"pyproject.toml": '[project]\nversion = "4.16.0"\n'}
        ).read
        with self.assertRaises(gen.check_doc_claims.ClaimError):
            gen.canonical_python_floor()


class BuildTests(_CanonicalSourceTestCase):
    def test_every_badge_states_its_canonical_value(self):
        by_name = {b.filename: b for b in gen.build_badges(test_count=42)}
        self.assertEqual(by_name["badge-license.svg"].message, "MIT")
        self.assertEqual(by_name["badge-python.svg"].message, "3.10+")
        self.assertEqual(by_name["badge-version.svg"].message, "4.16.0")
        self.assertEqual(by_name["badge-references.svg"].message, "2 papers")
        self.assertEqual(by_name["badge-tests.svg"].message, "42 passing")

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
                self.assertIn("GENERATED by", badge.render())
                self.assertIn("Source:", badge.render())


class RenderTests(_CanonicalSourceTestCase):
    def test_every_badge_is_well_formed_xml(self):
        for badge in gen.build_badges(test_count=42):
            with self.subTest(badge=badge.filename):
                ElementTree.fromstring(badge.render())

    def test_the_title_states_the_claim_for_screen_readers(self):
        by_name = {b.filename: b for b in gen.build_badges(test_count=42)}
        root = ElementTree.fromstring(by_name["badge-tests.svg"].render())
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
