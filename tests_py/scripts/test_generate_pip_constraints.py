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

_spec = importlib.util.spec_from_file_location(
    "generate_pip_constraints", REPO / "scripts" / "generate_pip_constraints.py"
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
            with self.subTest(constraint_set.filename):
                self.assertTrue(
                    (REPO / constraint_set.path()).is_file(),
                    f"{constraint_set.path()} is declared but not committed",
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
            command = constraint_set.command()
            with self.subTest(constraint_set.filename):
                self.assertIn("--locked", command)
                self.assertNotIn("--frozen", command)

    def test_export_is_captured_from_stdout(self) -> None:
        """`-o` makes uv write the invoking argv, including absolute paths."""
        for constraint_set in gen.SETS:
            with self.subTest(constraint_set.filename):
                self.assertNotIn("-o", constraint_set.command())
                self.assertNotIn("--output-file", constraint_set.command())


class TestDriftGate(unittest.TestCase):
    """A gate never observed failing is not a gate."""

    def test_check_passes_on_the_committed_tree(self) -> None:
        self.assertEqual(gen.main(["--check"]), 0)

    def test_check_fails_on_a_mutated_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            target = root / gen.SETS[0].path()
            target.write_text(
                target.read_text(encoding="utf-8").replace("==", "==0.0.0+", 1),
                encoding="utf-8",
            )
            with patch.object(gen, "REPO_ROOT", root):
                self.assertEqual(gen.main(["--check"]), 1)

    def test_check_fails_when_a_file_is_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            (root / gen.SETS[0].path()).unlink()
            with patch.object(gen, "REPO_ROOT", root):
                reason = gen.stale(gen.SETS[0])
            self.assertIsNotNone(reason)
            self.assertIn("missing", reason)

    def test_drift_message_names_the_regeneration_command(self) -> None:
        """The reader of a red gate must not have to guess the fix."""
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            (root / gen.SETS[0].path()).unlink()
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
        with patch.object(gen.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "idna==3.11\n"
            with self.assertRaises(gen.ExportError) as caught:
                gen.render(gen.SETS[0])
        self.assertIn("no hash", str(caught.exception))

    def test_empty_export_is_refused(self) -> None:
        """An export of nothing installs nothing and passes every later check."""
        with patch.object(gen.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "# only a comment\n"
            with self.assertRaises(gen.ExportError) as caught:
                gen.render(gen.SETS[0])
        self.assertIn("zero requirements", str(caught.exception))

    def test_export_failure_exits_two_not_one(self) -> None:
        """ "Could not run" must not read as "found no drift"."""
        with patch.object(gen, "stale", side_effect=gen.ExportError("uv exploded")):
            self.assertEqual(gen.main(["--check"]), 2)


if __name__ == "__main__":
    unittest.main()
