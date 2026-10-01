"""The installer-test uv stand-in must not hand pip a ``pylock.*.toml`` file.

CI failed with ``Invalid pylock file ... Expected '=' after a key`` because the
stand-in passed its requirements-format probe to pip under the launcher's
``pylock.cortex.toml`` name, which pip >= 26.2 parses as TOML.

source: ADR-1092"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests_py.scripts import _fake_uv

_RECORDER = (
    "import pathlib, sys\n"
    "pathlib.Path(sys.argv[0]).with_name('seen').write_text(\n"
    "    sys.argv[sys.argv.index('-r') + 1] + '\\n'\n"
    "    + pathlib.Path(sys.argv[sys.argv.index('-r') + 1]).read_text())\n"
)


def test_pip_receives_a_requirements_file_not_a_pylock_name(tmp_path: Path) -> None:
    requirements = tmp_path / "setup.txt"
    requirements.write_text("probe==1.0 --hash=sha256:00\n", encoding="utf-8")
    recorder = tmp_path / "recorder.py"
    recorder.write_text(_RECORDER, encoding="utf-8")
    directory = _fake_uv.install(
        tmp_path / "bin", requirements, pip=[sys.executable, str(recorder)]
    )
    pylock = tmp_path / "pylock.cortex.toml"
    pylock.write_text(requirements.read_text(), encoding="utf-8")

    done = subprocess.run(
        [str(directory / "uv"), "pip", "install", "--target", "t", "-r", str(pylock)],
        capture_output=True,
        text=True,
    )

    assert done.returncode == 0, done.stderr
    name, content = (tmp_path / "seen").read_text().split("\n", 1)
    assert Path(name).name == "requirements.txt"
    assert content == requirements.read_text()
