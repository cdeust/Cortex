"""A re-run on an up-to-date deps directory replaces no entry.

Issue #575: the idempotence guard matched a top-level entry to a distribution
by name, so every entry whose name is not its distribution's (``yaml``,
``google``, ``bin``, ...) was replaced on every install. The guard now reads
the owners of each entry from the scratch ``RECORD`` files.

These tests run real pip, offline, through the entry point both installers
call (``python3 scripts/launcher_deps.py --requirement FILE DEPS_DIR``),
against locally built wheels: ``cortexprobe-yaml`` ships the ``probeyaml``
package and a console script (so it owns ``bin``), and ``cortexprobe-ns-a``
and ``cortexprobe-ns-b`` share the ``probens`` namespace directory.

source: ADR-1064"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DEPS = REPO_ROOT / "scripts" / "launcher_deps.py"

_YAML = "cortexprobe-yaml"
_NS_A = "cortexprobe-ns-a"
_NS_B = "cortexprobe-ns-b"
_ENTRIES = ("probeyaml", "probens", "bin")


def _record_line(path: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"{path},sha256={digest.decode()},{len(data)}"


def _package_files(dist: str, version: str) -> dict[str, bytes]:
    code = f'VERSION = "{version}"\n\ndef main():\n    print(VERSION)\n'.encode()
    if dist == _YAML:
        return {"probeyaml/__init__.py": code}
    return {f"probens/{dist[-1]}/__init__.py": code}


def _build_wheel(wheels: Path, dist: str, version: str) -> Path:
    stem = f"{dist.replace('-', '_')}-{version}"
    dist_info = f"{stem}.dist-info"
    files = _package_files(dist, version)
    files[f"{dist_info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {dist}\nVersion: {version}\n"
    ).encode()
    files[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: cortex-test\n"
        b"Root-Is-Purelib: true\nTag: py3-none-any\n"
    )
    if dist == _YAML:
        files[f"{dist_info}/entry_points.txt"] = (
            b"[console_scripts]\nprobe-cli = probeyaml:main\n"
        )
    record = [_record_line(path, data) for path, data in files.items()]
    record.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = ("\n".join(record) + "\n").encode()
    wheel = wheels / f"{stem}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return wheel


def _write_requirements(layout: dict[str, Path], pins: dict[str, str]) -> None:
    lines = ["--no-index", f"--find-links {layout['wheels']}"]
    for dist, version in pins.items():
        wheel = _build_wheel(layout["wheels"], dist, version)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        lines.append(f"{dist}=={version} --hash=sha256:{digest}")
    layout["requirements"].write_text("\n".join(lines) + "\n", encoding="utf-8")


def _install(layout: dict[str, Path]) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER_DEPS),
            "--requirement",
            str(layout["requirements"]),
            str(layout["deps"]),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _inodes(deps: Path) -> dict[str, int]:
    return {p.name: p.stat().st_ino for p in deps.iterdir()}


@pytest.fixture
def layout(tmp_path: Path) -> dict[str, Path]:
    """A deps directory installed from pins at 1.0 for all three probes."""
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    layout = {
        "wheels": wheels,
        "deps": tmp_path / "data" / "deps",
        "requirements": tmp_path / "setup.txt",
    }
    _write_requirements(layout, {_YAML: "1.0", _NS_A: "1.0", _NS_B: "1.0"})
    _install(layout)
    assert {"probeyaml", "probens", "bin"} <= set(os.listdir(layout["deps"]))
    return layout


def test_rerun_on_matching_pins_keeps_every_entry(layout) -> None:
    before = _inodes(layout["deps"])
    _install(layout)
    assert _inodes(layout["deps"]) == before


def test_namespace_shared_by_two_distributions_is_replaced_on_a_bump(layout) -> None:
    before = _inodes(layout["deps"])
    _write_requirements(layout, {_YAML: "1.0", _NS_A: "1.0", _NS_B: "2.0"})
    _install(layout)
    after = _inodes(layout["deps"])
    deps = layout["deps"]
    assert after["probens"] != before["probens"]
    assert after["probeyaml"] == before["probeyaml"]
    assert after["bin"] == before["bin"]
    assert 'VERSION = "1.0"' in (deps / "probens/a/__init__.py").read_text()
    assert 'VERSION = "2.0"' in (deps / "probens/b/__init__.py").read_text()
    assert sorted(p.name for p in deps.glob("cortexprobe_ns_b-*.dist-info")) == [
        "cortexprobe_ns_b-2.0.dist-info"
    ]


def test_import_name_differing_from_the_distribution_is_replaced_on_a_bump(
    layout,
) -> None:
    before = _inodes(layout["deps"])
    _write_requirements(layout, {_YAML: "2.0", _NS_A: "1.0", _NS_B: "1.0"})
    _install(layout)
    after = _inodes(layout["deps"])
    assert after["probeyaml"] != before["probeyaml"]
    assert after["bin"] != before["bin"]
    assert after["probens"] == before["probens"]
    code = (layout["deps"] / "probeyaml" / "__init__.py").read_text()
    assert 'VERSION = "2.0"' in code


@pytest.mark.parametrize("entry", _ENTRIES)
def test_rerun_restores_an_entry_missing_under_matching_metadata(layout, entry) -> None:
    target = layout["deps"] / entry
    shutil.rmtree(target)
    _install(layout)
    assert target.is_dir()
