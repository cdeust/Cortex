"""CPU migration invalidates old ML success stamps without importing torch."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests_py.scripts._torch_cpu_fixture import distribution, pins

import launcher_deps as deps


class TestCpuStamps(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cortex-cpu-stamp-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, value in (
            ("_ML_PACKAGES", pins.ml_packages("linux")),
            ("ensure_deps", lambda path: None),
        ):
            replacement = patch.object(deps, target, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_previous_ml_stamp_does_not_satisfy_cpu_requirement(self) -> None:
        old = [spec for _name, spec in pins.ml_packages("darwin")]
        new = [spec for _name, spec in pins.ml_packages("linux")]
        deps._write_stamp(str(self.root), "ml", old)
        self.assertFalse(deps._pins_satisfied(str(self.root), "ml", new))

    def test_failed_cuda_repair_cannot_write_a_cpu_success_stamp(self) -> None:
        for name, spec in pins.ml_packages("darwin"):
            distribution(self.root, name, spec.split("==")[1])
        distribution(self.root, "torch", "2.13.0")
        old = [spec for _name, spec in pins.ml_packages("darwin")]
        deps._write_stamp(str(self.root), "ml", old)
        with patch.object(deps, "_pip_install", return_value=False) as pip:
            with patch.object(deps, "_importable", return_value=True) as imports:
                deps.ensure_all_deps(str(self.root))
        self.assertEqual(pip.call_args.args[1], [pins.TORCH_CPU_SPEC])
        imports.assert_not_called()
        new = [spec for _name, spec in pins.ml_packages("linux")]
        self.assertFalse(deps._pins_satisfied(str(self.root), "ml", new))

    def test_existing_cpu_stamp_skips_pip_and_heavy_imports(self) -> None:
        current = [spec for _name, spec in pins.ml_packages("linux")]
        deps._write_stamp(str(self.root), "ml", current)
        with patch.object(deps, "_pip_install") as pip:
            with patch.object(deps, "_importable") as imports:
                deps.ensure_all_deps(str(self.root))
        pip.assert_not_called()
        imports.assert_not_called()


if __name__ == "__main__":
    unittest.main()
