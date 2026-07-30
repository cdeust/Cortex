"""Tests for scripts/generate_pip_constraints.py — the hash-pin generator.

These files are the only thing standing between `--require-hashes` and a
failed CI leg, and every way they can be wrong is silent until an install
runs minutes later in a container. So the assertions here are about the
committed artifacts, not about the generator's internals: a test that
re-derives the file from the same code that wrote it proves nothing.

Written unittest-style to match the sibling script tests; pytest collects
unittest classes natively.

Independent oracle: the expected index directives are derived from uv.lock
by this file's own parser, never from the generator's helpers.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]

# The module name must be the dotted path mutmut derives from the file's
# location: it keys its mutant trampolines on
# "scripts.generate_pip_constraints.*", and a bare "generate_pip_constraints"
# makes every mutant look unreached, so a scoped mutation run stops early
# instead of scoring the suite (issue #262).
_spec = importlib.util.spec_from_file_location(
    "scripts.generate_pip_constraints",
    REPO / "scripts" / "generate_pip_constraints.py",
)
gen = importlib.util.module_from_spec(_spec)
# Registered before exec: @dataclass resolves its class's module through
# sys.modules, and raises AttributeError on a module that is not there yet.
sys.modules[_spec.name] = gen
_spec.loader.exec_module(gen)

# A requirements line pip treats as a requirement: not a comment, not a
# continuation (uv indents hashes), not a global option like --extra-index-url.
_REQUIREMENT = re.compile(r"^[A-Za-z0-9]")
# PEP 440 local version — `2.13.0+cpu`. Served by exactly one index, never PyPI.
_LOCAL_VERSION = re.compile(r"^([A-Za-z0-9._-]+)==([^\s;]*\+[^\s;]+)")
_PINNED = re.compile(r"^[A-Za-z0-9._-]+==[^\s;]+")
_PYPI = "https://pypi.org/simple"


def _requirement_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if _REQUIREMENT.match(line)]


def _committed_files() -> list[Path]:
    return sorted((REPO / "requirements").glob("*.txt"))


def _lock_registries() -> dict[tuple[str, str], str]:
    """(package, version) -> the registry uv.lock records it against."""
    registries: dict[tuple[str, str], str] = {}
    name = version = None
    for line in (REPO / "uv.lock").read_text(encoding="utf-8").splitlines():
        # Quoted prefixes: uv.lock opens with an unquoted `version = 1`.
        if line.startswith("[[package]]"):
            name = version = None
        elif line.startswith('name = "'):
            name = line.split('"')[1]
        elif line.startswith('version = "'):
            version = line.split('"')[1]
        elif line.startswith("source = ") and "registry" in line and name and version:
            registries[(name, version)] = line.split('"')[1]
    return registries


def _mirror(tmp: str) -> Path:
    """A working repo whose requirements/ can be mutated in isolation.

    Symlinks every other entry rather than copying: uv.lock alone is ~1 MB
    and uv must see a real pyproject.toml + uv.lock pair or `--locked`
    cannot assert anything.
    """
    root = Path(tmp) / "repo"
    root.mkdir()
    for entry in REPO.iterdir():
        if entry.name == "requirements":
            shutil.copytree(entry, root / "requirements")
        else:
            (root / entry.name).symlink_to(entry)
    return root


class TestSetTable(unittest.TestCase):
    """The table and the committed tree must agree in both directions."""

    def test_every_set_has_a_committed_file(self) -> None:
        for constraint_set in gen.SETS:
            path = gen.constraint_path(constraint_set)
            with self.subTest(constraint_set.filename):
                self.assertTrue(
                    (REPO / path).is_file(), f"{path} is declared but not committed"
                )

    def test_no_committed_file_is_orphaned(self) -> None:
        declared = {s.filename for s in gen.SETS}
        orphans = [f.name for f in _committed_files() if f.name not in declared]
        self.assertEqual(
            orphans,
            [],
            "requirements/ holds files no SET generates; --check would never"
            " notice them going stale",
        )

    def test_filenames_are_unique(self) -> None:
        names = [s.filename for s in gen.SETS]
        self.assertEqual(sorted(names), sorted(set(names)))

    def test_every_set_names_its_consumers(self) -> None:
        for constraint_set in gen.SETS:
            with self.subTest(constraint_set.filename):
                self.assertTrue(
                    constraint_set.consumers,
                    "a file nothing reads is a pin nothing refreshes",
                )


class TestHashCoverage(unittest.TestCase):
    """`--require-hashes` is all-or-nothing: one bare line aborts the install."""

    def test_every_requirement_is_version_pinned_and_hashed(self) -> None:
        for path in _committed_files():
            text = path.read_text(encoding="utf-8")
            requirements = _requirement_lines(text)
            with self.subTest(path.name):
                self.assertTrue(requirements, f"{path.name} exports nothing")
                for line in requirements:
                    self.assertRegex(line, _PINNED, f"{path.name}: not `name==version`")
                    self.assertTrue(
                        line.rstrip().endswith("\\"),
                        f"{path.name}: {line.strip()!r} carries no hash",
                    )
                self.assertIn("--hash=sha256:", text)

    def test_no_editable_or_directory_requirements(self) -> None:
        """Neither can be hashed — pip refuses both under --require-hashes."""
        for path in _committed_files():
            text = path.read_text(encoding="utf-8")
            with self.subTest(path.name):
                self.assertNotIn("\n-e ", text)
                self.assertNotIn("\n--editable", text)


class TestLocalVersionsCarryTheirIndex(unittest.TestCase):
    """A `+local` pin exists on one index only, and it is never PyPI.

    uv resolves such a wheel from a `[[tool.uv.index]]` but emits no index
    directive into the export, so a file that pins one without also naming
    its index cannot be installed at all: pip reports `No matching
    distribution found for torch==2.13.0+cpu` (reproduced against pip 26.1.2
    with a manylinux_2_28_x86_64 target). The failure is invisible on a
    macOS laptop, where the marker excludes the requirement, and lands only
    on the Linux runner that consumes the file.
    """

    def test_every_local_version_pin_names_a_serving_index(self) -> None:
        registries = _lock_registries()
        for path in _committed_files():
            text = path.read_text(encoding="utf-8")
            for line in _requirement_lines(text):
                match = _LOCAL_VERSION.match(line)
                if match is None:
                    continue
                name, version = match.group(1), match.group(2)
                registry = registries.get((name, version))
                with self.subTest(f"{path.name}:{name}=={version}"):
                    self.assertIsNotNone(
                        registry, f"{name}=={version} is in no uv.lock registry"
                    )
                    self.assertNotEqual(
                        registry, _PYPI, "PyPI does not serve local versions"
                    )
                    self.assertIn(
                        f"--extra-index-url {registry}",
                        text,
                        f"{path.name} pins {name}=={version} but never names"
                        f" {registry}; pip cannot resolve it",
                    )


class TestExportCommand(unittest.TestCase):
    """The invocation itself carries two guarantees worth pinning."""

    def test_export_asserts_the_lock_matches_pyproject(self) -> None:
        """`--frozen` exports a stale lock silently; `--locked` refuses to.

        With `--frozen`, a pyproject.toml edited but never re-locked still
        exports cleanly, so `--check` passes while the files describe a
        dependency set nobody declared.
        """
        for constraint_set in gen.SETS:
            command = gen.constraint_command(constraint_set)
            with self.subTest(constraint_set.filename):
                self.assertIn("--locked", command)
                self.assertNotIn("--frozen", command)

    def test_export_is_captured_from_stdout(self) -> None:
        """`-o` makes uv write the invoking argv, including absolute paths."""
        for constraint_set in gen.SETS:
            with self.subTest(constraint_set.filename):
                self.assertNotIn("-o", gen.constraint_command(constraint_set))
                self.assertNotIn(
                    "--output-file", gen.constraint_command(constraint_set)
                )


class TestDriftGate(unittest.TestCase):
    """A gate never observed failing is not a gate.

    These exercise the gate's DECISION — compare committed text against what
    the lock would produce, and map that to an exit code. They do not run uv.

    Whether the committed files actually agree with uv.lock right now is a
    fact about the working tree, not about this code, and it is already
    asserted by the Lint job (`generate_pip_constraints.py --check`) on every
    push and pull request. Asserting it here too did not make it truer: it
    made the unit suite require uv on PATH in every job that ran pytest, and
    when it was absent these tests failed with "uv is not installed" while
    testing nothing about drift. One gate, in the place that owns it.
    """

    def test_check_returns_zero_when_nothing_is_stale(self) -> None:
        with patch.object(gen, "stale", return_value=None):
            self.assertEqual(gen.main(["--check"]), 0)

    def test_check_fails_on_a_mutated_file(self) -> None:
        """The comparison itself: committed text != what the lock produces."""
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            target = root / gen.constraint_path(gen.SETS[0])
            committed = target.read_text(encoding="utf-8")
            target.write_text(committed.replace("==", "==0.0.0+", 1), encoding="utf-8")
            with patch.object(gen, "REPO_ROOT", root):
                # The lock is unchanged, so a correct render still yields the
                # original text; the mutated file must be reported.
                with patch.object(gen, "render", return_value=committed):
                    reason = gen.stale(gen.SETS[0])
                    self.assertIsNotNone(reason)
                    self.assertIn("uv.lock", reason)
                    self.assertEqual(gen.main(["--check"]), 1)

    def test_check_returns_zero_when_the_file_matches_the_render(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            committed = (root / gen.constraint_path(gen.SETS[0])).read_text(
                encoding="utf-8"
            )
            with patch.object(gen, "REPO_ROOT", root):
                with patch.object(gen, "render", return_value=committed):
                    self.assertIsNone(gen.stale(gen.SETS[0]))

    def test_check_fails_when_a_file_is_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            (root / gen.constraint_path(gen.SETS[0])).unlink()
            with patch.object(gen, "REPO_ROOT", root):
                reason = gen.stale(gen.SETS[0])
            self.assertIsNotNone(reason)
            self.assertIn("missing", reason)

    def test_drift_message_names_the_regeneration_command(self) -> None:
        """The reader of a red gate must not have to guess the fix."""
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            (root / gen.constraint_path(gen.SETS[0])).unlink()
            with patch.object(gen, "REPO_ROOT", root):
                reason = gen.stale(gen.SETS[0])
            self.assertIn("scripts/generate_pip_constraints.py", reason)


class TestFailureSignals(unittest.TestCase):
    """Every refusal emits its own reason, and they do not share exit codes."""

    _TORCH_CPU = "torch==2.13.0+cpu ; sys_platform == 'linux' \\\n"

    def test_undeclared_index_is_refused(self) -> None:
        """Naming an index pyproject.toml never opted into is not a fix."""
        with patch.object(gen, "declared_index_urls", return_value=frozenset()):
            with self.assertRaises(gen.ExportError) as caught:
                gen.serving_registries(self._TORCH_CPU)
        self.assertIn("[[tool.uv.index]]", str(caught.exception))

    def test_local_pin_absent_from_the_lock_is_refused(self) -> None:
        with self.assertRaises(gen.ExportError) as caught:
            gen.serving_registries("nosuchpkg==1.0.0+local \\\n")
        self.assertIn("no uv.lock registry", str(caught.exception))

    def test_unhashed_export_is_refused(self) -> None:
        """Against `compose`, not `render`: the rule is about the TEXT.

        These went through `render`, which reaches uv before it reaches any
        rule — so on a machine without uv they failed with "uv is not
        installed" and asserted nothing about hashing. Stubbing
        subprocess.run did not help, because the `shutil.which` guard ran
        first. The rule now has a pure entry point and the test needs no uv,
        no stub, and no PATH.
        """
        with self.assertRaises(gen.ExportError) as caught:
            gen.compose(gen.SETS[0], "idna==3.11\n")
        self.assertIn("no hash", str(caught.exception))

    def test_empty_export_is_refused(self) -> None:
        """An export of nothing installs nothing and passes every later check."""
        with self.assertRaises(gen.ExportError) as caught:
            gen.compose(gen.SETS[0], "# only a comment\n")
        self.assertIn("zero requirements", str(caught.exception))

    def test_export_failure_exits_two_not_one(self) -> None:
        """ "Could not run" must not read as "found no drift"."""
        with patch.object(gen, "stale", side_effect=gen.ExportError("uv exploded")):
            self.assertEqual(gen.main(["--check"]), 2)


if __name__ == "__main__":
    unittest.main()
