"""Pip resolution before dependency commit; stdlib only.

The CPU torch wheel is staged separately, then participates in the same PyPI
resolution as the requested ML packages. Base constraints retain the launcher's
shared dependency pins. PEP 668 retry remains limited to the private --target.
Sources: https://pip.pypa.io/en/stable/cli/pip_install/
https://pip.pypa.io/en/stable/topics/configuration/#pip-config-file
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import launcher_pins as _pins
import launcher_torch_cpu as _cpu


def clean_environment() -> dict[str, str]:
    """Disable inherited index overrides and all pip configuration files."""
    environment = dict(os.environ)
    for name in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_FIND_LINKS",
        "PIP_TRUSTED_HOST",
        "PIP_PYPI_URL",
        "PIP_NO_INDEX",
        "PIP_REQUIREMENT",
        "PIP_CONSTRAINT",
        "PIP_BUILD_CONSTRAINT",
    ):
        environment.pop(name, None)
    # source: pip configuration docs — os.devnull disables every config file.
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


@contextmanager
def constraint_args(deps_dir: str, constraints: list[str]) -> Iterator[list[str]]:
    """Delete the resolver hint on every exit, reporting any cleanup failure."""
    if not constraints:
        yield []
        return
    path = Path(f"{deps_dir}.constraints-{os.getpid()}.txt")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(constraints) + "\n")
    try:
        yield ["-c", str(path)]
    finally:
        try:
            path.unlink()
        except OSError as exc:
            print(
                f"[cortex-launcher] constraints cleanup failed: {exc}", file=sys.stderr
            )


def _install(
    command: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(command, capture_output=True, text=True, env=environment)
    error = (process.stderr or "") + (process.stdout or "")
    if process.returncode and "externally-managed-environment" in error:
        print(
            "[cortex-launcher] WARNING: pip reports an externally-managed "
            "Python environment (PEP 668). Retrying --break-system-packages "
            "for the plugin's private --target; system site-packages are untouched.",
            file=sys.stderr,
        )
        return subprocess.run(
            command + ["--break-system-packages"],
            capture_output=True,
            text=True,
            env=environment,
        )
    return process


def resolve(
    deps_dir: str, packages: list[str], constraints: list[str]
) -> subprocess.CompletedProcess[str]:
    """Resolve once into scratch; a CPU download failure aborts before install."""
    environment = clean_environment()
    if _cpu.required(packages):
        constraints = [*constraints, _pins.TORCH_CPU_SPEC]
    with constraint_args(deps_dir, constraints) as arguments:
        with _cpu.local_targets(deps_dir, packages, environment) as targets:
            command = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-q",
                "--index-url",
                "https://pypi.org/simple/",
                *arguments,
                "--target",
                f"{deps_dir}.tmp-{os.getpid()}",
                *targets,
            ]
            return _install(command, environment)
