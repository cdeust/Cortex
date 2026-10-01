"""The pip the launcher runs to bootstrap uv; stdlib only.

source: ADR-0751
source: ADR-1092"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


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


def run_install(
    command: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run one pip install, retrying once past a PEP 668 refusal for --target."""
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
    """The per-process install ``--target`` a commit later moves into ``deps_dir``."""
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
