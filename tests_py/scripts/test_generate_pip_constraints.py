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

import argparse
import importlib.util
import re
import shutil
import sys
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
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


class TestExport(unittest.TestCase):
    """``export()`` is the ONLY part of this module that touches the
    world (module docstring) -- a real ``uv`` on PATH, a subprocess.
    Isolated here so every other rule stays testable without one; these
    four cases are exactly the branches ``export()`` itself owns."""

    def test_raises_when_uv_is_not_on_path(self) -> None:
        """Exact message AND the exact probed name -- ``shutil.which``
        must be asked for literally "uv", not "UV" or some other case."""
        with patch.object(gen.shutil, "which", return_value=None) as which:
            with self.assertRaises(gen.ExportError) as caught:
                gen.export(gen.SETS[0])
        which.assert_called_once_with("uv")
        self.assertEqual(
            str(caught.exception),
            "uv is not installed — it is the only reader of uv.lock."
            " See https://docs.astral.sh/uv/getting-started/installation/",
        )

    def test_raises_when_uv_cannot_be_spawned(self) -> None:
        with patch.object(gen.shutil, "which", return_value="/usr/bin/uv"):
            with patch.object(
                gen.subprocess, "run", side_effect=OSError("no such file")
            ):
                with self.assertRaises(gen.ExportError) as caught:
                    gen.export(gen.SETS[0])
        self.assertEqual(str(caught.exception), "could not run uv: no such file")

    def test_raises_with_exact_command_and_stderr_on_nonzero_exit(self) -> None:
        result = SimpleNamespace(returncode=1, stdout="", stderr="  boom  \n")
        with patch.object(gen.shutil, "which", return_value="/usr/bin/uv"):
            with patch.object(gen.subprocess, "run", return_value=result):
                with self.assertRaises(gen.ExportError) as caught:
                    gen.export(gen.SETS[0])
        command = gen.constraint_command(gen.SETS[0])
        self.assertEqual(
            str(caught.exception),
            f"`{' '.join(command)}` failed with exit 1:\nboom",
        )

    def test_returns_stdout_and_invokes_the_declared_command_in_repo_root(
        self,
    ) -> None:
        result = SimpleNamespace(returncode=0, stdout="idna==3.11\n", stderr="")
        with patch.object(gen.shutil, "which", return_value="/usr/bin/uv"):
            with patch.object(gen.subprocess, "run", return_value=result) as run:
                output = gen.export(gen.SETS[0])
        self.assertEqual(output, "idna==3.11\n")
        # Every kwarg, not just cwd: a mutant dropping capture_output/text
        # or flipping check=False->True would otherwise slip through
        # unnoticed since the fake `result` answers either way.
        run.assert_called_once_with(
            gen.constraint_command(gen.SETS[0]),
            cwd=gen.REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )


class TestRender(unittest.TestCase):
    def test_composes_the_exported_body(self) -> None:
        body = "idna==3.11 \\\n    --hash=sha256:aa\n"
        with patch.object(gen, "export", return_value=body) as export:
            rendered = gen.render(gen.SETS[0])
        export.assert_called_once_with(gen.SETS[0])
        self.assertEqual(rendered, gen.compose(gen.SETS[0], body))


class TestWrite(unittest.TestCase):
    def test_returns_false_and_does_not_touch_disk_when_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            target = root / gen.constraint_path(gen.SETS[0])
            committed = target.read_text(encoding="utf-8")
            before = target.stat().st_mtime_ns
            with patch.object(gen, "REPO_ROOT", root):
                with patch.object(gen, "render", return_value=committed) as render:
                    changed = gen.write(gen.SETS[0])
            render.assert_called_once_with(gen.SETS[0])
            self.assertFalse(changed)
            self.assertEqual(target.stat().st_mtime_ns, before)

    def test_writes_and_returns_true_when_changed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            target = root / gen.constraint_path(gen.SETS[0])
            with patch.object(gen, "REPO_ROOT", root):
                with patch.object(
                    gen, "render", return_value="NEW CONTENT\n"
                ) as render:
                    changed = gen.write(gen.SETS[0])
            render.assert_called_once_with(gen.SETS[0])
            self.assertTrue(changed)
            self.assertEqual(target.read_text(encoding="utf-8"), "NEW CONTENT\n")

    def test_creates_every_missing_parent_directory(self) -> None:
        """``mkdir(parents=True, ...)``, not just the immediate parent: a
        REPO_ROOT that is itself two levels deep and entirely absent must
        still get every intermediate directory created. A single-level
        gap (only ``requirements/`` missing, its parent already present)
        cannot tell ``parents=True`` apart from ``parents=False`` --
        ``Path.mkdir`` only needs ``parents=True`` when a GRANDPARENT is
        also missing."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "not-yet" / "created-either"
            constraint_set = gen.SETS[0]
            with patch.object(gen, "REPO_ROOT", root):
                with patch.object(gen, "render", return_value="X\n"):
                    changed = gen.write(constraint_set)
            self.assertTrue(changed)
            target = root / gen.constraint_path(constraint_set)
            self.assertEqual(target.read_text(encoding="utf-8"), "X\n")


class TestIndexDirective(unittest.TestCase):
    """``compose()``'s error-path tests never reach this code (they all
    raise inside ``_reject_unusable`` first) -- exercised directly."""

    def test_empty_when_no_registries(self) -> None:
        self.assertEqual(gen._index_directive([]), "")

    def test_lists_every_registry_with_the_safety_rationale(self) -> None:
        """Exact, full-string equality -- a substring/prefix/suffix check
        (``assertIn``/``startswith``/``endswith``) survives a mutant that
        upper-cases or subtly retypes a word in the middle of the
        rationale comment, or swaps the URL-joining separator."""
        result = gen._index_directive(
            ["https://download.pytorch.org/whl/cpu", "https://example.invalid/simple"]
        )
        expected_reason = (
            "# An extra index widens where pip may look, which is normally how\n"
            "# dependency-confusion attacks land. It is safe HERE and only here\n"
            "# because every requirement in this file carries a hash and the file\n"
            "# is installed with --require-hashes: an artifact served by either\n"
            "# index that is not the locked one fails the hash check before it is\n"
            "# unpacked. Do not copy this directive into an unhashed file.\n"
        )
        expected_urls = (
            "--extra-index-url https://download.pytorch.org/whl/cpu\n"
            "--extra-index-url https://example.invalid/simple"
        )
        self.assertEqual(result, expected_reason + expected_urls + "\n\n")

    def test_single_registry_forms_exactly_one_directive_line(self) -> None:
        result = gen._index_directive(["https://example.invalid/simple"])
        directive_lines = [
            line for line in result.splitlines() if line.startswith("--extra-index-url")
        ]
        self.assertEqual(
            directive_lines, ["--extra-index-url https://example.invalid/simple"]
        )


class TestComposeSuccess(unittest.TestCase):
    """``compose()``'s SUCCESS path -- header + index directive + body --
    which every existing test bypasses by raising first."""

    def test_assembles_header_and_body_with_no_local_version_pins(self) -> None:
        body = "idna==3.11 \\\n    --hash=sha256:aa\n"
        result = gen.compose(gen.SETS[0], body)
        header = "\n".join(gen.constraint_header_lines(gen.SETS[0])) + "\n"
        self.assertEqual(result, header + body)

    def test_includes_the_index_directive_when_local_version_pins_exist(
        self,
    ) -> None:
        body = "torch==2.13.0+cpu \\\n    --hash=sha256:aa\n"
        with patch.object(
            gen,
            "serving_registries",
            return_value=["https://download.pytorch.org/whl/cpu"],
        ):
            result = gen.compose(gen.SETS[0], body)
        header = "\n".join(gen.constraint_header_lines(gen.SETS[0])) + "\n"
        index = gen._index_directive(["https://download.pytorch.org/whl/cpu"])
        self.assertEqual(result, header + index + body)


class TestDeclaredIndexUrls(unittest.TestCase):
    def test_extracts_every_declared_url(self) -> None:
        text = (
            "[[tool.uv.index]]\n"
            'name = "pytorch-cpu"\n'
            'url = "https://download.pytorch.org/whl/cpu"\n'
            "\n"
            "[[tool.uv.index]]\n"
            'name = "other"\n'
            'url = "https://example.invalid/simple"\n'
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(text, encoding="utf-8")
            with patch.object(gen, "REPO_ROOT", root):
                urls = gen.declared_index_urls()
        self.assertEqual(
            urls,
            frozenset(
                {
                    "https://download.pytorch.org/whl/cpu",
                    "https://example.invalid/simple",
                }
            ),
        )

    def test_reads_pyproject_toml_by_its_exact_lowercase_name(self) -> None:
        """A ``"pyproject.toml"``/``"PYPROJECT.TOML"`` mix-up would still
        find the real file on macOS's case-preserving-but-insensitive
        APFS (and even create/overwrite the SAME inode, so two files of
        differing case cannot coexist to prove the point that way) --
        captured as a plain Python STRING instead, which is always
        case-sensitive regardless of the filesystem underneath."""
        calls = []
        real_read_text = Path.read_text

        def capturing_read_text(path_self, *args, **kwargs):
            calls.append(path_self.name)
            return real_read_text(path_self, *args, **kwargs)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            with patch.object(gen, "REPO_ROOT", root):
                with patch.object(Path, "read_text", capturing_read_text):
                    gen.declared_index_urls()
        self.assertIn("pyproject.toml", calls)

    def test_empty_when_no_index_is_declared(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "x"\n', encoding="utf-8"
            )
            with patch.object(gen, "REPO_ROOT", root):
                urls = gen.declared_index_urls()
        self.assertEqual(urls, frozenset())


class TestLockRegistries(unittest.TestCase):
    _LOCK = (
        "version = 1\n"
        "revision = 1\n"
        "\n"
        "[[package]]\n"
        'name = "idna"\n'
        'version = "3.11"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
        "\n"
        "[[package]]\n"
        'name = "torch"\n'
        'version = "2.13.0+cpu"\n'
        'source = { registry = "https://download.pytorch.org/whl/cpu" }\n'
        "\n"
        "[[package]]\n"
        'name = "cortex"\n'
        'version = "0.1.0"\n'
        'source = { editable = "." }\n'
    )

    def test_parses_name_version_registry_triplets(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "uv.lock").write_text(self._LOCK, encoding="utf-8")
            with patch.object(gen, "REPO_ROOT", root):
                registries = gen.lock_registries()
        self.assertEqual(
            registries,
            {
                ("idna", "3.11"): "https://pypi.org/simple",
                ("torch", "2.13.0+cpu"): "https://download.pytorch.org/whl/cpu",
            },
        )

    def test_ignores_the_lock_formats_own_bare_version_line(self) -> None:
        """The unquoted ``version = 1`` at the top of the file is the LOCK
        FORMAT's own version, never a package's -- reading it as one
        would fabricate a spurious ``(None, "1")`` entry."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "uv.lock").write_text(self._LOCK, encoding="utf-8")
            with patch.object(gen, "REPO_ROOT", root):
                registries = gen.lock_registries()
        self.assertEqual(len(registries), 2)
        self.assertNotIn((None, "1"), registries)

    def test_non_registry_sources_are_excluded(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "uv.lock").write_text(self._LOCK, encoding="utf-8")
            with patch.object(gen, "REPO_ROOT", root):
                registries = gen.lock_registries()
        self.assertNotIn(("cortex", "0.1.0"), registries)

    def test_reads_uv_lock_by_its_exact_lowercase_name(self) -> None:
        """Same rationale as the pyproject.toml equivalent test: a
        "uv.lock"/"UV.LOCK" mix-up survives on macOS's case-insensitive
        APFS, so it is captured as a plain Python string instead."""
        calls = []
        real_read_text = Path.read_text

        def capturing_read_text(path_self, *args, **kwargs):
            calls.append(path_self.name)
            return real_read_text(path_self, *args, **kwargs)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "uv.lock").write_text(self._LOCK, encoding="utf-8")
            with patch.object(gen, "REPO_ROOT", root):
                with patch.object(Path, "read_text", capturing_read_text):
                    gen.lock_registries()
        self.assertIn("uv.lock", calls)

    def test_a_new_package_block_resets_the_carried_over_name_and_version(
        self,
    ) -> None:
        """Without the ``[[package]]`` reset, a block that (unusually)
        never assigns its OWN name before its ``source`` line would
        silently inherit the PRIOR block's identifier -- attributing an
        unrelated registry to the wrong (name, version) pair. Real
        ``uv.lock`` entries always carry their own name+version, so this
        constructs the one case that makes the reset's effect visible."""
        lock = (
            "[[package]]\n"
            'name = "idna"\n'
            'version = "3.11"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
            "\n"
            "[[package]]\n"
            'version = "9.9.9"\n'
            'source = { registry = "https://rogue.invalid/simple" }\n'
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "uv.lock").write_text(lock, encoding="utf-8")
            with patch.object(gen, "REPO_ROOT", root):
                registries = gen.lock_registries()
        self.assertEqual(registries, {("idna", "3.11"): "https://pypi.org/simple"})
        self.assertNotIn(("idna", "9.9.9"), registries)


class TestServingRegistriesSuccess(unittest.TestCase):
    """``serving_registries()``'s non-error decisions -- the existing
    ``TestFailureSignals`` cases cover only the two refusals."""

    def test_pypi_served_pins_need_no_index(self) -> None:
        with patch.object(
            gen, "lock_registries", return_value={("torch", "2.13.0+cpu"): gen.PYPI}
        ):
            self.assertEqual(gen.serving_registries("torch==2.13.0+cpu \\\n"), [])

    def test_dedupes_a_registry_needed_by_more_than_one_pin(self) -> None:
        body = "torch==2.13.0+cpu \\\ntorchvision==0.20.0+cpu \\\n"
        registries = {
            ("torch", "2.13.0+cpu"): "https://download.pytorch.org/whl/cpu",
            ("torchvision", "0.20.0+cpu"): "https://download.pytorch.org/whl/cpu",
        }
        with patch.object(gen, "lock_registries", return_value=registries):
            with patch.object(
                gen,
                "declared_index_urls",
                return_value=frozenset({"https://download.pytorch.org/whl/cpu"}),
            ):
                result = gen.serving_registries(body)
        self.assertEqual(result, ["https://download.pytorch.org/whl/cpu"])


class TestRejectUnusableExact(unittest.TestCase):
    """Exact messages, not substrings: a substring check (``assertIn``)
    survives a mutant that pads or subtly reorders the same words."""

    def test_exact_hash_count_and_first_offender_message(self) -> None:
        body = "a==1.0\nb==2.0 \\\n    --hash=sha256:aa\n"
        with self.assertRaises(gen.ExportError) as caught:
            gen._reject_unusable(gen.SETS[0], body)
        path = gen.constraint_path(gen.SETS[0])
        self.assertEqual(
            str(caught.exception),
            f"{path}: 1 requirement(s) carry no hash, first is 'a==1.0'",
        )

    def test_exact_zero_requirements_message(self) -> None:
        with self.assertRaises(gen.ExportError) as caught:
            gen._reject_unusable(gen.SETS[0], "# only a comment\n")
        path = gen.constraint_path(gen.SETS[0])
        self.assertEqual(
            str(caught.exception), f"{path}: export resolved to zero requirements"
        )

    def test_comments_continuations_and_options_are_not_requirements(self) -> None:
        body = (
            "# a comment\n"
            "--extra-index-url https://example.invalid/simple\n"
            "a==1.0 \\\n"
            "    --hash=sha256:aa\n"
        )
        gen._reject_unusable(gen.SETS[0], body)  # must not raise

    def test_hash_continuation_with_trailing_whitespace_is_still_recognized(
        self,
    ) -> None:
        """The hash-carrying check trims TRAILING whitespace before
        testing ``endswith("\\\\")`` -- a continuation line padded with a
        trailing space (as some `uv export` formattings do) must still
        read as hashed, not as a bare, unhashed requirement."""
        body = "a==1.0 \\ \n    --hash=sha256:aa\n"
        gen._reject_unusable(gen.SETS[0], body)  # must not raise


class TestMainOrchestration(unittest.TestCase):
    """``main()``'s own decisions -- exit code selection and the exact
    text of every message it prints -- isolated from ``stale``/``write``
    (see ``TestDriftGate``'s docstring for why those stay separate)."""

    def test_check_mode_prints_failures_and_returns_one(self) -> None:
        failing_set = gen.SETS[0]

        def fake_stale(constraint_set):
            return "boom: fix me" if constraint_set is failing_set else None

        with patch.object(gen, "stale", side_effect=fake_stale):
            with (
                patch("sys.stdout", new_callable=StringIO) as out,
                patch("sys.stderr", new_callable=StringIO) as err,
            ):
                code = gen.main(["--check"])
        self.assertEqual(code, 1)
        self.assertEqual(
            err.getvalue(),
            "Requirements files disagree with uv.lock:\n  boom: fix me\n",
        )
        self.assertEqual(out.getvalue(), "")

    def test_check_mode_prints_ok_count_and_returns_zero(self) -> None:
        with patch.object(gen, "stale", return_value=None):
            with patch("sys.stdout", new_callable=StringIO) as out:
                code = gen.main(["--check"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), f"requirements OK ({len(gen.SETS)} checked)\n")

    def test_write_mode_reports_each_changed_file_and_the_tally(self) -> None:
        changed_set = gen.SETS[0]

        def fake_write(constraint_set):
            return constraint_set is changed_set

        with patch.object(gen, "write", side_effect=fake_write):
            with patch("sys.stdout", new_callable=StringIO) as out:
                code = gen.main([])
        self.assertEqual(code, 0)
        expected = (
            f"wrote {gen.constraint_path(changed_set)}\n"
            f"1 of {len(gen.SETS)} file(s) changed\n"
        )
        self.assertEqual(out.getvalue(), expected)

    def test_write_mode_reports_zero_changed(self) -> None:
        with patch.object(gen, "write", return_value=False):
            with patch("sys.stdout", new_callable=StringIO) as out:
                code = gen.main([])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), f"0 of {len(gen.SETS)} file(s) changed\n")

    def test_write_mode_export_error_returns_two_with_message(self) -> None:
        with patch.object(gen, "write", side_effect=gen.ExportError("uv exploded")):
            with patch("sys.stderr", new_callable=StringIO) as err:
                code = gen.main([])
        self.assertEqual(code, 2)
        self.assertEqual(
            err.getvalue(), "constraint generation could not run: uv exploded\n"
        )


class TestMainArgumentParser(unittest.TestCase):
    """The parser's ``description``/``help`` strings are only observable
    through ``--help`` text (which argparse reflows/wraps, making an
    end-to-end capture fragile across terminal widths) -- captured at
    construction instead, with ``write`` stubbed so this never reaches a
    real ``uv`` invocation (module docstring: cold suite must not need
    one)."""

    def test_parser_uses_the_modules_docstring_and_exact_check_help(self) -> None:
        """Wraps the PRISTINE ``argparse.ArgumentParser`` in a plain
        factory function -- NOT a subclass. ``ArgumentParser.__init__``
        hardcodes ``super(ArgumentParser, self)`` against the real
        argparse module's own global, so patching that module's
        ``ArgumentParser`` NAME (even via subclassing) makes the
        original constructor recurse into itself infinitely; patching
        only the NAME ``argparse`` inside this module's namespace, to a
        stand-in whose ``ArgumentParser`` delegates to the untouched
        original class, avoids that entirely."""
        captured = {}
        real_argument_parser = argparse.ArgumentParser

        def capturing_parser_factory(*args, **kwargs):
            captured["description"] = kwargs.get("description")
            parser = real_argument_parser(*args, **kwargs)
            real_add_argument = parser.add_argument

            def capturing_add_argument(*a, **k):
                if a and a[0] == "--check":
                    captured["check_help"] = k.get("help")
                return real_add_argument(*a, **k)

            parser.add_argument = capturing_add_argument
            return parser

        fake_argparse = SimpleNamespace(ArgumentParser=capturing_parser_factory)
        with patch.object(gen, "argparse", fake_argparse):
            with patch.object(gen, "write", return_value=False):
                gen.main([])
        self.assertEqual(captured["description"], gen.__doc__)
        self.assertEqual(
            captured["check_help"],
            "do not write; exit 1 if any file is missing or disagrees with the lock",
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
                with patch.object(gen, "render", return_value=committed) as render:
                    self.assertIsNone(gen.stale(gen.SETS[0]))
            render.assert_called_once_with(gen.SETS[0])

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

    def test_missing_message_is_exact(self) -> None:
        """A substring check (``assertIn``, above) survives a mutant that
        pads or reorders the same words -- exact equality does not."""
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            path = gen.constraint_path(gen.SETS[0])
            (root / path).unlink()
            with patch.object(gen, "REPO_ROOT", root):
                reason = gen.stale(gen.SETS[0])
        self.assertEqual(
            reason, f"{path}: missing — run scripts/generate_pip_constraints.py"
        )

    def test_drift_message_is_exact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _mirror(tmp)
            path = gen.constraint_path(gen.SETS[0])
            with patch.object(gen, "REPO_ROOT", root):
                with patch.object(gen, "render", return_value="DIFFERENT\n"):
                    reason = gen.stale(gen.SETS[0])
        self.assertEqual(
            reason,
            f"{path}: disagrees with uv.lock — run scripts/generate_pip_constraints.py",
        )


class TestFailureSignals(unittest.TestCase):
    """Every refusal emits its own reason, and they do not share exit codes."""

    _TORCH_CPU = "torch==2.13.0+cpu ; sys_platform == 'linux' \\\n"

    def test_undeclared_index_is_refused(self) -> None:
        """Naming an index pyproject.toml never opted into is not a fix.

        Exact message, not a substring: a mutant that duplicates
        ``pin[1]`` in place of ``pin[0]`` (reporting "2.13.0+cpu==2.13.0
        +cpu" instead of "torch==2.13.0+cpu") still contains
        "[[tool.uv.index]]" and would survive an ``assertIn``-only check.
        """
        with patch.object(
            gen,
            "lock_registries",
            return_value={
                ("torch", "2.13.0+cpu"): "https://download.pytorch.org/whl/cpu"
            },
        ):
            with patch.object(gen, "declared_index_urls", return_value=frozenset()):
                with self.assertRaises(gen.ExportError) as caught:
                    gen.serving_registries(self._TORCH_CPU)
        self.assertEqual(
            str(caught.exception),
            "torch==2.13.0+cpu resolves from https://download.pytorch.org/whl/cpu,"
            " which pyproject.toml declares no [[tool.uv.index]] for",
        )

    def test_local_pin_absent_from_the_lock_is_refused(self) -> None:
        """Exact message: same duplicated-``pin[1]`` mutant as above would
        report "1.0.0+local==1.0.0+local" instead of naming the package."""
        with self.assertRaises(gen.ExportError) as caught:
            gen.serving_registries("nosuchpkg==1.0.0+local \\\n")
        self.assertEqual(
            str(caught.exception), "nosuchpkg==1.0.0+local is in no uv.lock registry"
        )

    def test_a_non_local_version_line_does_not_stop_the_scan(self) -> None:
        """``continue``, not ``break``, on a non-matching line -- a plain
        pin ahead of a local-version one must not cut the scan short."""
        body = "idna==3.11\ntorch==2.13.0+cpu \\\n"
        with patch.object(
            gen,
            "lock_registries",
            return_value={
                ("torch", "2.13.0+cpu"): "https://download.pytorch.org/whl/cpu"
            },
        ):
            with patch.object(
                gen,
                "declared_index_urls",
                return_value=frozenset({"https://download.pytorch.org/whl/cpu"}),
            ):
                result = gen.serving_registries(body)
        self.assertEqual(result, ["https://download.pytorch.org/whl/cpu"])

    def test_a_duplicate_registry_does_not_stop_the_scan(self) -> None:
        """``continue``, not ``break``, on an already-needed registry -- a
        THIRD pin needing a DIFFERENT registry after a duplicate must
        still be collected."""
        body = (
            "torch==2.13.0+cpu \\\ntorchvision==0.20.0+cpu \\\nother==1.0.0+rocm \\\n"
        )
        registries = {
            ("torch", "2.13.0+cpu"): "https://download.pytorch.org/whl/cpu",
            ("torchvision", "0.20.0+cpu"): "https://download.pytorch.org/whl/cpu",
            ("other", "1.0.0+rocm"): "https://download.pytorch.org/whl/rocm",
        }
        with patch.object(gen, "lock_registries", return_value=registries):
            with patch.object(
                gen,
                "declared_index_urls",
                return_value=frozenset(
                    {
                        "https://download.pytorch.org/whl/cpu",
                        "https://download.pytorch.org/whl/rocm",
                    }
                ),
            ):
                result = gen.serving_registries(body)
        self.assertEqual(
            result,
            [
                "https://download.pytorch.org/whl/cpu",
                "https://download.pytorch.org/whl/rocm",
            ],
        )

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
