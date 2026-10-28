#!/usr/bin/env python3
"""Run the real Claude installation probe on the launcher's pinned Python.

Source: ADR-1092/1104 and the existing scripts/install_e2e acceptance probe.
Only runtime preparation changes; the host still installs the plugin itself.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from ci_environment import isolated_environment
import launcher_layout
import launcher_python

ROOT = Path(__file__).resolve().parent.parent


def probe(work: Path, settle: str) -> int:
    deps = launcher_layout.project_deps_dir(work / "data", ROOT)
    python = launcher_python.provide(deps)
    return subprocess.run(
        [
            python,
            str(ROOT / "scripts/install_e2e/run.py"),
            "--python",
            python,
            "--marketplace",
            str(ROOT),
            "--work",
            str(work / "machine"),
            "--settle-seconds",
            settle,
        ],
        cwd=work,
        check=False,
    ).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--settle-seconds", required=True)
    parser.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args()
    work = args.work.resolve()
    if args.bootstrap:
        return probe(work, args.settle_seconds)
    work.mkdir(parents=True, exist_ok=False)
    for directory in ("home", "data", "tmp"):
        (work / directory).mkdir()
    return subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--work",
            str(work),
            "--settle-seconds",
            args.settle_seconds,
            "--bootstrap",
        ],
        cwd=work,
        env=isolated_environment(work, dict(os.environ)),
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
