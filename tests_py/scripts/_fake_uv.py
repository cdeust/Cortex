"""An offline stand-in for the pinned uv, for installer tests.

``uv export`` writes a prepared hash-pinned probe requirement; ``uv pip
install`` hands it to real pip with ``--require-hashes`` into the scratch
``--target`` the launcher chose. Everything else is refused.

source: ADR-1092"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"

_SCRIPT = """#!{python}
import subprocess, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("uv {version} (cortex test stand-in)")
elif args[0] == "export":
    out = args[args.index("--output-file") + 1]
    open(out, "w").write(open({requirements!r}).read())
elif args[:2] == ["pip", "install"]:
    target = args[args.index("--target") + 1]
    sys.exit(subprocess.run([*{pip!r}, "install", "-q", "--no-deps",
        "--require-hashes", "--target", target, "-r", args[-1]]).returncode)
else:
    sys.exit(f"unexpected uv call: {{args}}")
"""


def _launcher(name: str):
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return __import__(name)


def install(directory: Path, requirements: Path) -> Path:
    """Write ``directory/uv`` at the pinned version, installing ``requirements``."""
    directory.mkdir(parents=True, exist_ok=True)
    uv = directory / "uv"
    uv.write_text(
        _SCRIPT.format(
            python=sys.executable,
            version=_launcher("launcher_uv").UV_VERSION,
            requirements=str(requirements),
            pip=_launcher("launcher_pip").pip_entry(),
        ),
        encoding="utf-8",
    )
    uv.chmod(0o755)
    return directory


def path_with(directory: Path) -> str:
    return f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"
