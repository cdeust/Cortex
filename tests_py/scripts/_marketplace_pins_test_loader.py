"""Shared module loader for the check_marketplace_pins.py test files.

Split out of test_check_marketplace_pins.py (issue: that file crossed the
300-line §4.1 cap once PIN_VERSION_UNPUBLISHED coverage was added) so both
test_check_marketplace_pins.py and test_check_marketplace_pins_sha_manifest.py
import the exact same `gate` module object — one dotted spec load, not two
independent ones that could see divergent module-level mutable state
(FROZEN_PINS/PENDING_PINS) across the split.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

# Dotted to match the path-derived name mutmut keys mutant trampolines on
# ("scripts.check_marketplace_pins.*") — a bare module name makes every
# mutant look unreached to a scoped mutation run (issue #262).
_spec = importlib.util.spec_from_file_location(
    "scripts.check_marketplace_pins",
    Path(__file__).resolve().parents[2] / "scripts" / "check_marketplace_pins.py",
)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def git_repo_with_tags(root: str, tags: list[str]) -> Path:
    p = Path(root)
    subprocess.run(["git", "-C", root, "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", root, "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )
    for t in tags:
        subprocess.run(["git", "-C", root, "tag", t], check=True)
    return p
