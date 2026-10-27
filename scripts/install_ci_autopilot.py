#!/usr/bin/env python3
"""Install the local Codex dispatcher as a per-user macOS launchd service.

source: launchd.plist(5), ProgramArguments/StartInterval/RunAtLoad.
Owner request2026-10-27.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

LABEL = "com.cortex.codex-autopilot"


def copy_runtime(options, root):
    source = Path(__file__).resolve().parent
    for name in ("ci_autopilot.py", "ci_autopilot_queue.py", "ci_autopilot_issues.py"):
        shutil.copyfile(source / name, root / name)
    brief = source.parent / "docs/automation/codex-worker.md"
    shutil.copyfile(brief, root / "codex-worker.md")
    contract = (
        options.contract.read_text()
        .split("## Contract — paste this into the delegation prompt\n", 1)[1]
        .split("\n---\n\n## Orchestrator side", 1)[0]
    )
    (root / "contract.md").write_text(contract)
    manifest = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in (
            "ci_autopilot.py",
            "ci_autopilot_queue.py",
            "ci_autopilot_issues.py",
            "codex-worker.md",
            "contract.md",
        )
    }
    (root / "installed-sha256.json").write_text(json.dumps(manifest, indent=2))


def install(options):
    if sys.platform != "darwin":
        raise RuntimeError("This installer targets macOS launchd")
    if options.interval <= 0:
        raise ValueError("Polling interval must be positive")
    root = options.runtime.resolve()
    root.mkdir(parents=True, exist_ok=True)
    copy_runtime(options, root)
    arguments = [
        sys.executable,
        "-B",
        str(root / "ci_autopilot.py"),
        "--repo",
        str(options.repo.resolve()),
        "--state",
        str(root / "state.json"),
        "--brief",
        str(root / "codex-worker.md"),
    ]
    configuration = {
        "Label": LABEL,
        "ProgramArguments": arguments,
        "StartInterval": options.interval,
        "RunAtLoad": True,
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        },
        "StandardOutPath": str(root / "dispatcher.log"),
        "StandardErrorPath": str(root / "dispatcher-error.log"),
    }
    plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps(configuration))
    if options.enable:
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True
        )
    print(plist)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--interval", type=int, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--enable", action="store_true")
    install(parser.parse_args())


if __name__ == "__main__":
    main()
