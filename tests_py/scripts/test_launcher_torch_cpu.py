"""Routing, partial repair and rollback tests without network or real wheels."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from tests_py.scripts._torch_cpu_fixture import (
    CpuInstallFixture,
    distribution,
    install,
    pins,
)


class TestCpuInstall(CpuInstallFixture):
    def test_linux_ml_uses_hash_checked_cpu_wheel_then_pypi(self) -> None:
        self.assertTrue(
            install.pip_install(str(self.deps), ["sentence-transformers==5.6.1"])
        )
        download, resolve = self.calls
        command = download["command"]
        self.assertIn("--no-deps", command)
        self.assertIn("--only-binary=:all:", command)
        self.assertIn("--require-hashes", command)
        self.assertEqual(
            command[command.index("--index-url") + 1], pins.TORCH_CPU_INDEX
        )
        self.assertTrue(download["requirements"].startswith(pins.TORCH_CPU_SPEC + " "))
        self.assertTrue(
            all(digest in download["requirements"] for digest in pins.TORCH_CPU_HASHES)
        )
        command = resolve["command"]
        self.assertEqual(
            command[command.index("--index-url") + 1], "https://pypi.org/simple/"
        )
        self.assertIn(pins.TORCH_CPU_SPEC, resolve["constraints"])
        self.assertTrue(any(item.endswith(".whl") for item in command))
        self.assertNotIn("--extra-index-url", command)
        self.assertFalse(list(self.root.glob(".cortex-torch-*")))

    def test_partial_install_keeps_cpu_pin_when_torch_is_already_present(self) -> None:
        distribution(self.deps, "torch", "2.13.0+cpu")
        before = (self.deps / "torch/__init__.py").read_bytes()
        self.assertTrue(
            install.pip_install(
                str(self.deps), ["sentence-transformers==5.6.1"], ["numpy==2.5.1"]
            )
        )
        self.assertEqual(len(self.calls), 2)
        self.assertIn("numpy==2.5.1", self.calls[-1]["constraints"])
        self.assertIn(pins.TORCH_CPU_SPEC, self.calls[-1]["constraints"])
        self.assertTrue(
            any("torch-2.13.0+cpu-" in item for item in self.calls[-1]["command"])
        )
        self.assertEqual((self.deps / "torch/__init__.py").read_bytes(), before)

    def test_mac_resolution_preserves_pypi_only_behavior(self) -> None:
        with patch.object(sys, "platform", "darwin"):
            self.assertTrue(
                install.pip_install(str(self.deps), ["sentence-transformers==5.6.1"])
            )
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("download", self.calls[0]["command"])
        self.assertNotIn("-c", self.calls[0]["command"])
        self.assertFalse(any("torch" in item for item in self.calls[0]["command"]))

    def test_external_pip_config_and_index_overrides_are_ignored(self) -> None:
        hostile = {
            name: "https://fixture.invalid"
            for name in (
                "PIP_INDEX_URL",
                "PIP_EXTRA_INDEX_URL",
                "PIP_FIND_LINKS",
                "PIP_TRUSTED_HOST",
                "PIP_CONFIG_FILE",
                "PIP_REQUIREMENT",
                "PIP_CONSTRAINT",
                "PIP_BUILD_CONSTRAINT",
                "PIP_NO_INDEX",
                "PIP_PYPI_URL",
            )
        }
        with patch.dict(os.environ, hostile):
            self.assertTrue(install.pip_install(str(self.deps), ["flashrank==0.2.10"]))
        for call in self.calls:
            self.assertEqual(call["environment"]["PIP_CONFIG_FILE"], os.devnull)
            self.assertTrue(
                all(
                    name not in call["environment"]
                    for name in hostile
                    if name != "PIP_CONFIG_FILE"
                )
            )

    def test_hash_failure_aborts_without_install_or_commit(self) -> None:
        distribution(self.deps, "torch", "2.13.0")
        before = (self.deps / "torch/__init__.py").read_bytes()
        failure = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="HASHES DO NOT MATCH"
        )
        with patch.object(install.subprocess, "run", return_value=failure) as runner:
            with patch.object(install, "_commit_resolved_entries") as commit:
                with redirect_stderr(io.StringIO()) as diagnostic:
                    result = install.pip_install(str(self.deps), [pins.TORCH_CPU_SPEC])
        self.assertFalse(result)
        self.assertEqual(runner.call_count, 1)
        commit.assert_not_called()
        self.assertIn("HASHES DO NOT MATCH", diagnostic.getvalue())
        self.assertEqual((self.deps / "torch/__init__.py").read_bytes(), before)
        self.assertFalse(list(self.root.glob(".cortex-torch-*")))

    def test_wrong_or_missing_download_is_refused_without_fallback(self) -> None:
        success = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.object(install.subprocess, "run", return_value=success) as runner:
            with redirect_stderr(io.StringIO()) as diagnostic:
                result = install.pip_install(str(self.deps), [pins.TORCH_CPU_SPEC])
        self.assertFalse(result)
        self.assertEqual(runner.call_count, 1)
        self.assertIn("exactly the pinned torch wheel", diagnostic.getvalue())

    def test_cpu_commit_failure_restores_old_torch_and_preserves_retry(self) -> None:
        distribution(self.deps, "torch", "2.13.0")
        before = (self.deps / "torch/__init__.py").read_bytes()
        temporary = Path(f"{self.deps}.tmp-{os.getpid()}")
        original = os.replace

        def fail_torch(source, target):
            if Path(source) == temporary / "torch":
                raise PermissionError("fixture locked torch")
            return original(source, target)

        with patch.object(install.os, "replace", side_effect=fail_torch):
            with redirect_stderr(io.StringIO()) as diagnostic:
                result = install.pip_install(str(self.deps), [pins.TORCH_CPU_SPEC])
        self.assertFalse(result)
        self.assertEqual((self.deps / "torch/__init__.py").read_bytes(), before)
        self.assertTrue((temporary / "torch/__init__.py").is_file())
        self.assertIn("preserved for manual recovery", diagnostic.getvalue())

    def test_pep668_retries_install_with_same_cpu_wheel_and_constraints(self) -> None:
        failed_once = False

        def run(command, **options):
            nonlocal failed_once
            if "install" in command and not failed_once:
                failed_once = True
                return subprocess.CompletedProcess(
                    command, 1, stdout="", stderr="externally-managed-environment"
                )
            return self.fake_pip(command, **options)

        with patch.object(install.subprocess, "run", side_effect=run) as runner:
            with redirect_stderr(io.StringIO()) as diagnostic:
                result = install.pip_install(
                    str(self.deps), ["sentence-transformers==5.6.1"]
                )
        self.assertTrue(result)
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[-1], commands[-2] + ["--break-system-packages"])
        self.assertIn(pins.TORCH_CPU_SPEC, self.calls[-1]["constraints"])
        self.assertIn("PEP 668", diagnostic.getvalue())


if __name__ == "__main__":
    unittest.main()
