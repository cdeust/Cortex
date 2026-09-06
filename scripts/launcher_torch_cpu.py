"""Resolve only torch through the explicit CPU index; bootstrap stdlib only.

The download is hash-checked against the lock export, then supplied as a local
wheel to the ordinary PyPI resolution. --extra-index-url cannot express uv's
package-specific explicit index rule: pip searches all indexes without priority.
Sources: https://pip.pypa.io/en/stable/cli/pip_download/
https://pip.pypa.io/en/stable/cli/pip_install/#finding-packages
https://docs.astral.sh/uv/concepts/indexes/#pinning-a-package-to-an-index
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import launcher_deps_fs as _fs
import launcher_pins as _pins


class CpuWheelError(RuntimeError):
    """CPU-only resolution failed; never fall back to a PyPI torch wheel."""


def required(packages: list[str]) -> bool:
    """A partial Linux ML install still resolves torch from its CPU source."""
    ml_names = {name for name, _spec in _pins.ml_packages("linux")}
    return sys.platform == "linux" and any(
        _fs.parse_pip_spec(spec)[0] in ml_names for spec in packages
    )


def download_command(wheel_dir: Path) -> list[str]:
    """Build a single-distribution, binary-only, hash-checked download."""
    requirement = wheel_dir / "torch.txt"
    hashes = " ".join(f"--hash=sha256:{digest}" for digest in _pins.TORCH_CPU_HASHES)
    requirement.write_text(f"{_pins.TORCH_CPU_SPEC} {hashes}\n", encoding="utf-8")
    return [
        sys.executable,
        "-m",
        "pip",
        "download",
        "-q",
        "--no-deps",
        "--only-binary=:all:",
        "--index-url",
        _pins.TORCH_CPU_INDEX,
        "--require-hashes",
        "-r",
        str(requirement),
        "--dest",
        str(wheel_dir),
    ]


def _download(wheel_dir: Path, environment: dict[str, str]) -> Path:
    process = subprocess.run(
        download_command(wheel_dir), capture_output=True, text=True, env=environment
    )
    if process.returncode:
        raise CpuWheelError(
            f"CPU torch download failed: {process.stderr or process.stdout}"
        )
    wheels = list(wheel_dir.glob("*.whl"))
    if len(wheels) != 1 or not wheels[0].name.startswith(
        "torch-" + _pins.TORCH_CPU_SPEC.split("==")[1] + "-"
    ):
        raise CpuWheelError(
            "CPU torch download did not produce exactly the pinned torch wheel"
        )
    return wheels[0]


@contextmanager
def local_targets(
    deps_dir: str, packages: list[str], environment: dict[str, str]
) -> Iterator[list[str]]:
    """The temporary wheel survives resolution, then is removed; pip owns its cache."""
    if not required(packages):
        yield packages
        return
    with tempfile.TemporaryDirectory(
        prefix=".cortex-torch-", dir=Path(deps_dir).parent
    ) as temporary:
        wheel = _download(Path(temporary), environment)
        others = [spec for spec in packages if _fs.parse_pip_spec(spec)[0] != "torch"]
        yield [*others, str(wheel)]
