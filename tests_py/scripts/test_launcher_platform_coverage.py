"""Every platform the launcher served before ADR-1092 still gets a coherent set.

``uv export`` writes the launcher's two sets from uv.lock and
``uv pip install --dry-run --python-platform`` resolves them for a platform
without installing anything, offline. Two failures this guards:

- onnxruntime / torch publish ``macosx_14_0_arm64`` wheels only from 1.24 /
  2.12, so one locked version would leave Intel Macs and Apple Silicon before
  macOS 14 without a stack (``tool.uv`` cannot express that, the
  ``platform-bounds`` group does);
- PyTorch stops at 2.2.2 on Intel Macs, which needs numpy 1 and transformers 4,
  and cryptography 49+ has no Intel wheel.

uv emulates ``aarch64-apple-darwin`` with an old ``platform_release``, so that
platform stands for macOS before 14; the macOS 14+ fork is asserted on the
lock's own markers.

source: ADR-1092"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pytest itself depends on tomli below 3.11
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import launcher_sets  # noqa: E402

LINUX_X86 = "x86_64-manylinux_2_28"
LINUX_ARM = "aarch64-manylinux_2_28"
WINDOWS = "x86_64-pc-windows-msvc"
MAC_INTEL = "x86_64-apple-darwin"
MAC_OLD_ARM = "aarch64-apple-darwin"
PYTHONS = ("3.10", "3.11", "3.12", "3.13", "3.14")
NO_WHEEL = re.compile(r"Package `(torch|onnxruntime)` can't be installed because it")

# ML cells with no wheel anywhere: PyTorch publishes none for Intel Macs past
# CPython 3.12, onnxruntime none for Apple Silicon before macOS 14 past 3.13.
UNSERVED = {(MAC_INTEL, "3.13"), (MAC_INTEL, "3.14"), (MAC_OLD_ARM, "3.14")}


def _major_minor(version: str) -> tuple[int, int]:
    numbers = re.match(r"(\d+)\.(\d+)", version)
    assert numbers, version
    return int(numbers.group(1)), int(numbers.group(2))


@pytest.fixture(scope="module")
def uv() -> str:
    path = shutil.which("uv")
    assert path, "uv must be on PATH (CONTRIBUTING.md, check_venv_lock_parity)"
    return path


@pytest.fixture(scope="module")
def empty_env(uv: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An empty environment, so a dry run lists the whole closure."""
    path = tmp_path_factory.mktemp("env")
    subprocess.run([uv, "venv", "--quiet", "--no-config", str(path)], check=True)
    return path / ("Scripts" if sys.platform == "win32" else "bin") / "python"


@pytest.fixture(scope="module")
def pylocks(uv: str, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    out = {}
    for name, args in (("base", launcher_sets.BASE), ("ml", launcher_sets.ML)):
        path = tmp_path_factory.mktemp(name) / f"pylock.{name}.toml"
        subprocess.run(
            [uv, "export", "--quiet", "--frozen", "--no-config", "--project",
             str(REPO), "--no-emit-project", "--no-default-groups", *args,
             "--format", "pylock.toml", "--output-file", str(path)],
            check=True,
        )  # fmt: skip
        out[name] = path
    return out


def _resolve(uv: str, env: Path, pylock: Path, platform: str, python: str):
    """(returncode, {package: version}, stderr) of a hash-pinned dry run."""
    done = subprocess.run(
        [uv, "pip", "install", "--dry-run", "--offline", "--no-build",
         "--no-config", "--preview-features", "pylock", "--python",
         str(env), "--python-platform", platform, "--python-version",
         python, "-r", str(pylock)],
        capture_output=True,
        text=True,
    )  # fmt: skip
    picked = dict(re.findall(r"^ \+ (\S+)==(\S+)$", done.stdout + done.stderr, re.M))
    return done.returncode, picked, done.stderr


@pytest.mark.parametrize("python", PYTHONS)
@pytest.mark.parametrize(
    "platform", (LINUX_X86, LINUX_ARM, WINDOWS, MAC_INTEL, MAC_OLD_ARM)
)
def test_base_set_resolves_to_wheels_everywhere(
    uv, empty_env, pylocks, platform, python
) -> None:
    code, picked, stderr = _resolve(uv, empty_env, pylocks["base"], platform, python)
    assert code == 0, stderr
    assert "numpy" in picked


@pytest.mark.parametrize("python", PYTHONS)
@pytest.mark.parametrize(
    "platform", (LINUX_X86, LINUX_ARM, WINDOWS, MAC_INTEL, MAC_OLD_ARM)
)
def test_ml_set_resolves_to_a_coherent_stack(
    uv, empty_env, pylocks, platform, python
) -> None:
    code, picked, stderr = _resolve(uv, empty_env, pylocks["ml"], platform, python)
    if (platform, python) in UNSERVED:
        assert code != 0 and NO_WHEEL.search(stderr), stderr  # loud, never a fallback
        return
    assert code == 0, stderr
    torch, ort = _major_minor(picked["torch"]), _major_minor(picked["onnxruntime"])
    transformers = _major_minor(picked["transformers"])[0]
    numpy = _major_minor(picked["numpy"])[0]
    if platform == MAC_INTEL:
        # the last torch built for Intel, its numpy 1 ABI, a transformers it runs
        assert (torch, numpy, transformers, ort) == ((2, 2), 1, 4, (1, 23))
    elif platform == MAC_OLD_ARM:
        assert (2, 4) <= torch < (2, 12) and ort == (1, 23)
        assert (numpy, transformers) == (2, 5)
    else:
        assert torch >= (2, 12) and numpy == 2 and transformers == 5
        assert ort >= (1, 24) or python == "3.10"


def test_macos_14_and_later_keep_the_newest_torch_and_onnxruntime() -> None:
    lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    newest = {
        name: max(
            (
                p
                for p in lock["package"]
                if p["name"] == name and "+" not in p["version"]
            ),
            key=lambda p: _major_minor(p["version"]),
        )
        for name in ("torch", "onnxruntime")
    }
    for name, package in newest.items():
        markers = " ".join(package["resolution-markers"])
        assert "platform_release >= '23'" in markers, name
        assert "platform_release < '23'" not in markers, name
