"""Reconcile CPU version/hash/source policy with the committed lock export."""

from __future__ import annotations

import re
import unittest

from tests_py.scripts._torch_cpu_fixture import SCRIPTS, pins


class TestCpuPins(unittest.TestCase):
    def test_linux_only_pin_matches_export_and_hashes(self) -> None:
        exported = (SCRIPTS.parent / "requirements/setup.txt").read_text()
        line = next(
            line
            for line in exported.splitlines()
            if line.startswith("torch==") and "sys_platform == 'linux'" in line
        )
        self.assertEqual(pins.TORCH_CPU_SPEC, line.split(" ;", 1)[0])
        block = exported.split(line, 1)[1].split("\n    #", 1)[0]
        hashes = set(re.findall(r"--hash=sha256:([a-f0-9]+)", block))
        self.assertTrue(hashes)
        self.assertEqual(set(pins.TORCH_CPU_HASHES), hashes)
        self.assertIn(("torch", pins.TORCH_CPU_SPEC), pins.ml_packages("linux"))
        self.assertEqual(pins.ml_packages("darwin"), pins.ml_packages("win32"))
        self.assertFalse(any(name == "torch" for name, _ in pins.ml_packages("darwin")))

    def test_hashes_and_cpu_source_match_uv_lock(self) -> None:
        lock = (SCRIPTS.parent / "uv.lock").read_text()
        block = next(
            block
            for block in lock.split("[[package]]")
            if '\nname = "torch"' in block and '\nversion = "2.13.0+cpu"' in block
        )
        self.assertIn(f'registry = "{pins.TORCH_CPU_INDEX}"', block)
        hashes = set(re.findall(r'hash = "sha256:([a-f0-9]+)"', block))
        self.assertEqual(set(pins.TORCH_CPU_HASHES), hashes)
        config = (SCRIPTS.parent / "pyproject.toml").read_text()
        index = next(
            block
            for block in config.split("[[tool.uv.index]]")
            if 'name = "pytorch-cpu"' in block
        )
        self.assertIn(f'url = "{pins.TORCH_CPU_INDEX}"', index)
        self.assertIn("explicit = true", index)


if __name__ == "__main__":
    unittest.main()
