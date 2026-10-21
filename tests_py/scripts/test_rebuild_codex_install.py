"""The Codex rebuild script (ADR-1112): dry run by default, same-commit plan.

The real build and install are not run by the suite (they replace the
developer's uv tool environment); the plan they execute is checked here.

source: ADR-1112
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "rebuild_codex_install.py"


def test_default_is_a_dry_run_that_changes_nothing():
    done = subprocess.run(
        [sys.executable, str(_SCRIPT)], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0
    lines = done.stdout.splitlines()
    assert lines[0].startswith("uv build --wheel --out-dir")
    assert lines[1].startswith("uv tool install --force --python")
    assert "--no-build" in lines[1]
    assert "hypermnesia-mcp[postgresql,sqlite] @" in lines[1]
    assert lines[-1] == "dry run: nothing changed; add --yes to build and install"


def test_the_plan_builds_from_this_checkout():
    sys.path.insert(0, str(_REPO / "scripts"))
    import rebuild_codex_install as script  # noqa: PLC0415 -- script module

    build, install = script.plan(Path("/tmp/wheels"), "/usr/bin/python3")
    assert build[-1] == str(_REPO)
    assert install[install.index("--python") + 1] == "/usr/bin/python3"
