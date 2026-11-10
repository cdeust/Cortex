"""PATH lookup must reach the uv stand-in, never the machine's real uv.

On Windows the stand-in was an extensionless ``uv``: ``shutil.which`` skips a
name outside ``PATHEXT``, so the launcher ran the runner's real uv on the real
uv.lock and the probe packages were never installed (issue #692, class 9).

source: ADR-1092
source: https://docs.python.org/3/library/shutil.html#shutil.which"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from tests_py.scripts import _fake_uv


def test_path_lookup_resolves_to_the_stand_in(tmp_path: Path) -> None:
    directory = _fake_uv.install(tmp_path / "bin", tmp_path / "setup.txt")

    found = shutil.which("uv", path=str(directory))

    assert found is not None
    assert Path(found).resolve() == _fake_uv.executable(directory).resolve()


def test_windows_stand_in_runs_the_script_with_this_interpreter(
    tmp_path: Path,
) -> None:
    directory = _fake_uv.install(tmp_path / "bin", tmp_path / "setup.txt", windows=True)

    wrapper = _fake_uv.executable(directory, windows=True)
    assert wrapper.name == "uv.cmd"
    assert not (directory / "uv").exists()
    assert wrapper.read_bytes() == (
        f'@"{sys.executable}" "%~dp0uv-stand-in.py" %*\r\n'.encode()
    )
    version = subprocess.run(
        [sys.executable, str(directory / "uv-stand-in.py"), "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    pinned = _fake_uv._launcher("launcher_uv").UV_VERSION
    assert version.stdout.startswith(f"uv {pinned} ")
