"""Pip resolution before dependency commit; stdlib only.

source: ADR-0751"""

from __future__ import annotations

import importlib.util
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
    # source: ADR-0751
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


def scratch_dir(deps_dir: str) -> str:
    """The per-process pip ``--target`` a commit later moves into ``deps_dir``."""
    return f"{deps_dir}.tmp-{os.getpid()}"


def bundled_pip_wheel() -> Path | None:
    """The pip wheel the standard library carries for ``ensurepip``, if any.

    CPython ships one under ``ensurepip/_bundled`` (packaging specification,
    *ensurepip — Bootstrapping the pip installer*); Debian's `python3-minimal`
    removes the package entirely, which is the ``None`` case.

    source: ADR-1067"""
    spec = importlib.util.find_spec("ensurepip")
    if spec is None or not spec.origin:
        return None
    wheels = sorted((Path(spec.origin).parent / "_bundled").glob("pip-*.whl"))
    return wheels[-1] if wheels else None


def pip_entry() -> list[str]:
    """How to run pip on this interpreter, in order of preference.

    An installed ``pip`` module first. Otherwise the stdlib's bundled wheel,
    run in place from its own path — a wheel is a zip Python imports directly,
    so this installs nothing and leaves the interpreter untouched. A venv made
    by ``uv venv`` or ``python -m venv --without-pip`` has no pip module and
    reaches the second case (issue #582).

    Raises ``FileNotFoundError`` when the interpreter has neither.

    source: ADR-1067"""
    if importlib.util.find_spec("pip") is not None:
        return [sys.executable, "-m", "pip"]
    wheel = bundled_pip_wheel()
    if wheel is None:
        raise FileNotFoundError(
            f"{sys.executable} has no pip module and its standard library "
            "bundles no pip wheel for ensurepip. Install pip for that "
            "interpreter, or run the launcher with one that has it."
        )
    return [sys.executable, str(wheel / "pip")]


def _pip_command(*arguments: str) -> list[str]:
    return [
        *pip_entry(),
        "install",
        "-q",
        "--index-url",
        "https://pypi.org/simple/",
        *arguments,
    ]


def resolve(
    deps_dir: str, packages: list[str], constraints: list[str]
) -> subprocess.CompletedProcess[str]:
    """Resolve once into scratch; a CPU download failure aborts before install."""
    environment = clean_environment()
    if _cpu.required(packages):
        constraints = [*constraints, _pins.TORCH_CPU_SPEC]
    with constraint_args(deps_dir, constraints) as arguments:
        with _cpu.local_targets(deps_dir, packages, environment) as targets:
            command = _pip_command(
                *arguments, "--target", scratch_dir(deps_dir), *targets
            )
            return _install(command, environment)


def install_requirements(
    deps_dir: str, requirements: str
) -> subprocess.CompletedProcess[str]:
    """Install a generated, hash-pinned closure file into scratch.

    source: ADR-1059
    source: ADR-1063"""
    command = _pip_command(
        "--target",
        scratch_dir(deps_dir),
        "--no-deps",
        "--require-hashes",
        "-r",
        requirements,
    )
    return _install(command, clean_environment())
