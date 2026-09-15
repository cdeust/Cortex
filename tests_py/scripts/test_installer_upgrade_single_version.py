"""An installer upgrade leaves exactly one version of each package in deps/.

Issue #573: ``scripts/setup.sh`` (the ``--postgres`` path of
``install-plugin.sh``) and ``scripts/setup.py`` ran ``pip install --target``
straight into the persistent deps directory. pip then skipped every package
directory that already existed but still added the new ``*.dist-info``, so an
upgrade left old code under new metadata. Both installers now go through the
launcher's scratch-and-commit install.

These tests run real pip, offline, against two locally built wheels of a probe
distribution. The requirements file carries the same flags as
``requirements/setup.txt`` would need offline (``--no-index``,
``--find-links``) and a hash-pinned line, so ``--require-hashes`` and
``--no-deps`` are exercised for real.

source: ADR-1063"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIB_PATH = SCRIPTS_DIR / "lib" / "install_python_deps.sh"
SETUP_PY = SCRIPTS_DIR / "setup.py"
SETUP_SH = SCRIPTS_DIR / "setup.sh"

_DIST = "cortexprobe"
_OLD = "1.0"
_NEW = "2.0"

_HARNESS = """
set -euo pipefail
ok()   {{ echo "[ok] $1"; }}
fail() {{ echo "[FAIL] $1"; exit 1; }}
source "{lib_path}"
install_python_deps_step "{scripts_dir}" "{requirements}" "{deps_dir}"
"""


def _record_line(path: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"{path},sha256={digest.decode()},{len(data)}"


def _build_wheel(wheels: Path, version: str) -> Path:
    dist_info = f"{_DIST}-{version}.dist-info"
    files = {
        f"{_DIST}/__init__.py": f'VERSION = "{version}"\n'.encode(),
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {_DIST}\nVersion: {version}\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: cortex-test\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    record = [_record_line(path, data) for path, data in files.items()]
    record.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = ("\n".join(record) + "\n").encode()
    wheel = wheels / f"{_DIST}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return wheel


def _pip_target(deps: Path, wheels: Path, version: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "--no-index",
            "--find-links",
            str(wheels),
            "--target",
            str(deps),
            f"{_DIST}=={version}",
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def layout(tmp_path: Path) -> dict[str, Path]:
    """A deps directory at version N and a requirements file pinning N+1."""
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _build_wheel(wheels, _OLD)
    new_wheel = _build_wheel(wheels, _NEW)
    deps = tmp_path / "data" / "deps"
    _pip_target(deps, wheels, _OLD)
    wheel_hash = hashlib.sha256(new_wheel.read_bytes()).hexdigest()
    requirements = tmp_path / "setup.txt"
    requirements.write_text(
        f"--no-index\n--find-links {wheels}\n"
        f"{_DIST}=={_NEW} --hash=sha256:{wheel_hash}\n",
        encoding="utf-8",
    )
    return {"wheels": wheels, "deps": deps, "requirements": requirements}


def _as_left_by_4_22_0(layout: dict[str, Path]) -> None:
    """Reproduce the mixed state a direct ``--target`` upgrade produced:
    version N code under both the N and N+1 ``*.dist-info``."""
    scratch = layout["deps"].parent / "n1"
    _pip_target(scratch, layout["wheels"], _NEW)
    new_dist_info = f"{_DIST}-{_NEW}.dist-info"
    os.replace(scratch / new_dist_info, layout["deps"] / new_dist_info)


def _assert_single_pinned_version(deps: Path) -> None:
    dist_infos = sorted(p.name for p in deps.glob(f"{_DIST}-*.dist-info"))
    assert dist_infos == [f"{_DIST}-{_NEW}.dist-info"], dist_infos
    code = (deps / _DIST / "__init__.py").read_text(encoding="utf-8")
    assert f'VERSION = "{_NEW}"' in code, code
    leftovers = [p.name for p in deps.parent.iterdir() if ".tmp-" in p.name]
    leftovers += [p.name for p in deps.iterdir() if ".bak-" in p.name]
    assert not leftovers, leftovers


def _run_setup_sh_step(layout: dict[str, Path]) -> subprocess.CompletedProcess:
    script = _HARNESS.format(
        lib_path=LIB_PATH,
        scripts_dir=SCRIPTS_DIR,
        requirements=layout["requirements"],
        deps_dir=layout["deps"],
    )
    python_bin = str(Path(sys.executable).parent)
    env = {"PATH": f"{python_bin}{os.pathsep}/usr/bin:/bin", "HOME": os.environ["HOME"]}
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env
    )


def _run_setup_py_install_deps(layout: dict[str, Path], monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("scripts.setup", SETUP_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DEPS_DIR", str(layout["deps"]))
    monkeypatch.setattr(module, "_SETUP_CONSTRAINTS", layout["requirements"])
    module.install_deps()


@pytest.mark.parametrize("mixed", [False, True], ids=["from-N", "from-4.22.0-mix"])
def test_setup_sh_step_leaves_only_the_pinned_version(layout, mixed) -> None:
    if mixed:
        _as_left_by_4_22_0(layout)
    result = _run_setup_sh_step(layout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[ok] Python packages installed" in result.stdout
    _assert_single_pinned_version(layout["deps"])


@pytest.mark.parametrize("mixed", [False, True], ids=["from-N", "from-4.22.0-mix"])
def test_setup_py_install_deps_leaves_only_the_pinned_version(
    layout, mixed, monkeypatch
) -> None:
    if mixed:
        _as_left_by_4_22_0(layout)
    _run_setup_py_install_deps(layout, monkeypatch)
    _assert_single_pinned_version(layout["deps"])


def test_setup_sh_step_fails_loudly_when_the_install_fails(layout) -> None:
    layout["requirements"].write_text(
        f"--no-index\n--find-links {layout['wheels']}\n{_DIST}=={_NEW} "
        f"--hash=sha256:{'0' * 64}\n",
        encoding="utf-8",
    )
    result = _run_setup_sh_step(layout)
    assert result.returncode != 0
    assert "[FAIL] Dependency install failed" in result.stdout
    assert sorted(p.name for p in layout["deps"].glob(f"{_DIST}-*.dist-info")) == [
        f"{_DIST}-{_OLD}.dist-info"
    ]


def test_setup_sh_routes_step_3_through_the_library() -> None:
    """The library is what the tests above drive; setup.sh must call it with
    the generated closure, not keep a direct ``--target`` install of its own."""
    text = SETUP_SH.read_text(encoding="utf-8")
    assert 'source "$SCRIPT_DIR/lib/install_python_deps.sh"' in text
    assert (
        'install_python_deps_step "$SCRIPT_DIR" '
        '"$PROJECT_DIR/requirements/setup.txt" "$DEPS_DIR"'
    ) in text
    assert "--target" not in text
