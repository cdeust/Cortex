"""An offline stand-in for the pinned uv, for installer tests.

``uv export`` writes a prepared hash-pinned probe requirement; ``uv pip
install`` hands it to real pip with ``--require-hashes`` into the scratch
``--target`` the launcher chose. Everything else is refused.

The launcher names the exported file ``pylock.*.toml``, as real uv needs. The
probe is a requirements-format file, and pip >= 26.2 parses any file with that
name as TOML, so the stand-in gives pip a ``requirements.txt`` copy instead.

source: ADR-1092"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"

_SCRIPT = """#!{python}
import pathlib, shutil, subprocess, sys, tempfile
args = sys.argv[1:]
if args == ["--version"]:
    print("uv {version} (cortex test stand-in)")
elif args[0] == "export":
    out = args[args.index("--output-file") + 1]
    open(out, "w").write(open({requirements!r}).read())
elif args[:2] == ["pip", "install"]:
    target = args[args.index("--target") + 1]
    with tempfile.TemporaryDirectory() as scratch:
        requirement = pathlib.Path(scratch) / "requirements.txt"
        shutil.copyfile(args[-1], requirement)
        sys.exit(subprocess.run([*{pip!r}, "install", "-q", "--no-deps",
            "--require-hashes", "--target", target, "-r", str(requirement)]
            ).returncode)
else:
    sys.exit(f"unexpected uv call: {{args}}")
"""


def _launcher(name: str):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return __import__(name)


def install(directory: Path, requirements: Path, pip: list[str] | None = None) -> Path:
    """Write ``directory/uv`` at the pinned version, installing ``requirements``."""
    directory.mkdir(parents=True, exist_ok=True)
    uv = directory / "uv"
    uv.write_text(
        _SCRIPT.format(
            python=sys.executable,
            version=_launcher("launcher_uv").UV_VERSION,
            requirements=str(requirements),
            pip=pip or _launcher("launcher_pip").pip_entry(),
        ),
        encoding="utf-8",
    )
    uv.chmod(0o755)
    return directory


def path_with(directory: Path) -> str:
    return f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"
