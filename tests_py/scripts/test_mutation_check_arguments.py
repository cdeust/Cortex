"""``scripts/mutation_check.sh`` refuses an empty test list identically on every bash.

An empty list used to reach ``"${TEST_ARR[@]}"`` under ``set -u``: bash 3.2.57
(macOS ``/bin/bash``) aborted there with "unbound variable" before any work,
newer bash ran the tool on no tests (issue #690 sibling search).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mutation_check.sh"
BASHES = sorted(
    {
        path
        for path in ("/bin/bash", shutil.which("bash"))
        if path and os.access(path, os.X_OK)
    }
)


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_an_empty_test_list_is_a_usage_error(bash: str) -> None:
    done = subprocess.run(
        [bash, str(SCRIPT), "", "mcp_server/core/x.py"],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2
    assert "test list (first argument) is empty" in done.stderr
    assert "unbound variable" not in done.stderr
